"""Ordonnanceur du Market Watcher (CDC3 sections 54 et 88).

C'est ce module qui rend le sous-systeme autonome : il demarre avec le Bridge
et n'a besoin de personne pour tourner.

Quatre boucles independantes. Une panne des actualites ne doit pas suspendre
le suivi des signaux, et une erreur sur un instrument ne doit pas emporter les
autres. Chaque boucle survit a ses propres pannes et reprend au tour suivant
(CDC3 section 55).

Le watcher n'envoie AUCUN ordre. Il n'importe jamais le moteur d'execution :
c'est structurel, pas une case a decocher (CDC3 section 44).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.config.logging_config import get_logger
from app.config.settings import APP_VERSION
from app.database.session import session_scope
from app.models.core import utcnow
from app.models.intelligence import NewsImpact
from app.repositories import news_repo
from app.services import journal
from app.services.market_data.provider import market_engine
from app.services.trading.symbol_resolver import SymbolResolver
from app.watcher import formatter, learning, repository
from app.watcher.config import WatcherConfig, load_config
from app.watcher.engine import AnalysisOutcome, WatcherEngine
from app.watcher.lifecycle import LifecycleTracker
from app.watcher.models import STRATEGY_VERSION
from app.watcher.publisher import TelegramPublisher, telegram_publisher

logger = get_logger(__name__)

# Delais de premier demarrage, en secondes. Le watcher laisse MetaTrader, la
# session Telegram et le moteur d'actualites se mettre en place avant de
# produire quoi que ce soit.
ANALYSIS_WARMUP = 75.0
LIFECYCLE_WARMUP = 45.0
NEWS_WARMUP = 150.0
MAINTENANCE_WARMUP = 300.0

# Repos plancher entre deux tours : empeche l'emballement si un tour echoue
# en une fraction de seconde.
FLOOR_SECONDS = 5.0
MAINTENANCE_EVERY_SECONDS = 3600.0
NEWS_EVERY_SECONDS = 300.0
# Duree de conservation des traces d'analyse, en jours.
ANALYSIS_RETENTION_DAYS = 30
# Au-dela, une depeche sans portee marche n'apprend plus rien.
NEWS_RETENTION_HOURS = 1
# Age maximal d'une actualite pour meriter encore une alerte.
NEWS_MAX_AGE_MINUTES = 30


@dataclass
class LoopState:
    """Etat observable d'une boucle, pour le diagnostic."""

    name: str
    running: bool = False
    last_run_at: datetime | None = None
    last_error: str | None = None
    runs: int = 0
    failures: int = 0
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "running": self.running,
            "lastRunAt": self.last_run_at.isoformat() if self.last_run_at else None,
            "lastError": self.last_error,
            "runs": self.runs,
            "failures": self.failures,
            "detail": self.detail,
        }


@dataclass
class WatcherState:
    """Photographie complete du sous-systeme, exposee par l'API."""

    analysis: LoopState = field(default_factory=lambda: LoopState("analysis"))
    lifecycle: LoopState = field(default_factory=lambda: LoopState("lifecycle"))
    news: LoopState = field(default_factory=lambda: LoopState("news"))
    maintenance: LoopState = field(default_factory=lambda: LoopState("maintenance"))
    started_at: datetime | None = None
    resolved_symbols: dict[str, str] = field(default_factory=dict)
    unavailable_symbols: list[str] = field(default_factory=list)
    last_outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "strategyVersion": STRATEGY_VERSION,
            "loops": {
                "analysis": self.analysis.to_dict(),
                "lifecycle": self.lifecycle.to_dict(),
                "news": self.news.to_dict(),
                "maintenance": self.maintenance.to_dict(),
            },
            "resolvedSymbols": dict(self.resolved_symbols),
            "unavailableSymbols": list(self.unavailable_symbols),
            "lastOutcomes": dict(self.last_outcomes),
        }


class WatcherScheduler:
    """Fait vivre le Market Watcher pendant toute la duree du Bridge."""

    def __init__(self, publisher: TelegramPublisher | None = None) -> None:
        self._publisher = publisher or telegram_publisher
        self._engine = WatcherEngine(self._publisher)
        self._tracker = LifecycleTracker(self._publisher)
        self.state = WatcherState()
        self._tasks: list[asyncio.Task[None]] = []
        self._announced = False
        self._notified_news: set[int] = set()
        # Point de depart du balayage, avance d'un cran a chaque tour.
        self._rotation = 0

    @property
    def started(self) -> bool:
        return bool(self._tasks)

    @property
    def publisher(self) -> TelegramPublisher:
        return self._publisher

    @property
    def engine(self) -> WatcherEngine:
        """Moteur de decision, expose pour les analyses a la demande."""
        return self._engine

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._tasks:
            return
        self.state.started_at = utcnow()
        self._tasks = [
            asyncio.create_task(self._analysis_loop(), name="watcher-analysis"),
            asyncio.create_task(self._lifecycle_loop(), name="watcher-lifecycle"),
            asyncio.create_task(self._news_loop(), name="watcher-news"),
            asyncio.create_task(self._maintenance_loop(), name="watcher-maintenance"),
        ]
        logger.info(
            "AI Market Watcher demarre (%s) : analyse, suivi, actualites, entretien",
            STRATEGY_VERSION,
        )

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            # L'arret ne doit jamais echouer : une boucle qui meurt mal ne doit
            # pas empecher le Bridge de se fermer proprement.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []
        for loop in (self.state.analysis, self.state.lifecycle, self.state.news, self.state.maintenance):
            loop.running = False

    # ------------------------------------------------------------------
    # Un tour de chaque boucle, isole pour etre testable seul
    # ------------------------------------------------------------------
    async def run_analysis_once(self, symbols: list[str] | None = None) -> list[AnalysisOutcome]:
        """Analyse chaque instrument surveille, l'un apres l'autre.

        Sequentiel volontairement : MetaTrader supporte mal les appels
        concurrents, et un tour complet reste largement plus court que la
        periode d'analyse.
        """
        outcomes: list[AnalysisOutcome] = []
        async with session_scope() as session:
            config = await load_config(session)
            if not config.enabled:
                self.state.analysis.detail = "Watcher desactive dans les reglages."
                return outcomes

            engine = market_engine()
            if engine is None:
                self.state.analysis.detail = "Aucune source de marche attachee."
                return outcomes

            wanted = symbols if symbols is not None else config.symbols
            available = await self._resolve_symbols(session, engine, wanted)
            for canonical, broker_symbol in self._rotated(available, rotate=symbols is None):
                try:
                    outcome = await self._engine.analyse(
                        session, engine, canonical, broker_symbol, config
                    )
                except Exception as exc:
                    # Un instrument en panne ne doit pas arreter les autres.
                    logger.warning("Analyse de %s impossible : %s", canonical, exc)
                    continue
                outcomes.append(outcome)
                self.state.last_outcomes[canonical] = {
                    "decision": outcome.decision.value,
                    "score": round(outcome.score, 1),
                    "detail": outcome.detail,
                    "at": utcnow().isoformat(),
                }

        published = sum(1 for outcome in outcomes if outcome.published)
        self.state.analysis.detail = (
            f"{len(outcomes)} instrument(s) analyse(s), {published} message(s) publie(s)"
        )
        return outcomes

    async def run_lifecycle_once(self) -> dict[str, Any]:
        async with session_scope() as session:
            config = await load_config(session)
            if not config.enabled:
                return {"skipped": "Watcher desactive."}
            engine = market_engine()
            if engine is None:
                return {"skipped": "Aucune source de marche attachee."}
            report = await self._tracker.run_once(session, engine, config)
        self.state.lifecycle.detail = (
            f"{report.checked} signal(aux) suivi(s), {report.updated} mise(s) a jour"
        )
        return report.to_dict()

    async def run_news_once(self) -> int:
        """Relaie dans le canal les actualites majeures deja collectees.

        Le watcher ne collecte pas : le moteur d'actualites du Bridge remplit
        deja ces tables. On ne relaie que ce qui est recent, majeur, et jamais
        deux fois.
        """
        sent = 0
        async with session_scope() as session:
            config = await load_config(session)
            if not config.enabled or not config.send_news_alerts:
                return 0
            since = utcnow() - timedelta(minutes=NEWS_MAX_AGE_MINUTES)
            try:
                events = await news_repo.recent_news(session, since)
            except Exception as exc:
                logger.debug("Actualites illisibles pour le watcher : %s", exc)
                return 0

            for event in events:
                if event.id is None or event.id in self._notified_news:
                    continue
                if event.impact not in (NewsImpact.HIGH, NewsImpact.CRITICAL):
                    continue
                if event.duplicate_of is not None:
                    continue
                text = formatter.breaking_news_message(
                    headline=event.title,
                    source=event.source,
                    impact=event.impact.value,
                    sentiment=event.sentiment.value,
                    affected=list(event.affected_assets or []) or list(event.affected_currencies or []),
                )
                result = await self._publisher.publish(session, text, config)
                self._notified_news.add(event.id)
                if result.sent:
                    sent += 1
        # La memoire des depeches deja relayees est bornee : sans cela elle
        # grossirait indefiniment sur un Bridge qui tourne des semaines.
        if len(self._notified_news) > 2000:
            self._notified_news = set(sorted(self._notified_news)[-1000:])
        self.state.news.detail = f"{sent} alerte(s) d'actualite relayee(s)"
        return sent

    async def run_maintenance_once(self) -> int:
        async with session_scope() as session:
            removed = await repository.purge_analyses(
                session, utcnow() - timedelta(days=ANALYSIS_RETENTION_DAYS)
            )
            # Les depeches sans portee marche saturent la liste : impact
            # faible, tonalite neutre, aucun instrument rattache. Passe une
            # heure, elles n'apprennent plus rien a personne.
            depeches = await news_repo.purge_unimportant(
                session, utcnow() - timedelta(hours=NEWS_RETENTION_HOURS)
            )
            # L'apprentissage ecarte ce qui n'a jamais gagne. Jamais bloquant :
            # une panne de sa part ne doit pas suspendre l'entretien, qui est
            # le seul a borner la croissance des tables.
            with contextlib.suppress(Exception):
                config = await load_config(session)
                for decision in await learning.review(session, config):
                    await self._publisher.publish(session, decision.message, config)
        self.state.maintenance.detail = (
            f"{removed} trace(s) d'analyse et {depeches} depeche(s) sans portee effacees"
        )
        return removed + depeches

    def _rotated(
        self, available: dict[str, str], rotate: bool = True
    ) -> list[tuple[str, str]]:
        """Ordre de balayage, decale d'un cran a chaque tour.

        MetaTrader peut cesser de repondre en plein cycle : son processus est
        alors tue et tout ce qui suit echoue. En balayant toujours dans le meme
        ordre, ce seraient systematiquement les memes instruments de fin de
        liste qui ne seraient jamais analyses. La rotation garantit que chacun
        passe en tete a tour de role.
        """
        items = list(available.items())
        if not rotate or len(items) < 2:
            return items
        decalage = self._rotation % len(items)
        self._rotation += 1
        return items[decalage:] + items[:decalage]

    # ------------------------------------------------------------------
    # Resolution des instruments
    # ------------------------------------------------------------------
    async def _resolve_symbols(
        self, session: Any, engine: Any, wanted: list[str]
    ) -> dict[str, str]:
        """Ne garde que les instruments reellement presents chez le broker.

        Aucun instrument n'est suppose disponible : ceux que le compte n'a pas
        sont ecartes et signales, jamais analyses sur des donnees inventees.
        """
        resolver = SymbolResolver(engine.service)
        resolved: dict[str, str] = {}
        missing: list[str] = []
        for raw in wanted:
            canonical = raw.strip().upper()
            if not canonical:
                continue
            try:
                match = await resolver.resolve(session, canonical)
            except Exception as exc:
                logger.debug("Resolution de %s impossible : %s", canonical, exc)
                match = None
            if match is None:
                missing.append(canonical)
                continue
            resolved[canonical] = match.broker_symbol

        self.state.resolved_symbols = dict(resolved)
        self.state.unavailable_symbols = missing
        if missing:
            logger.info(
                "Instruments absents du compte, ignores par le watcher : %s",
                ", ".join(missing),
            )
        return resolved

    # ------------------------------------------------------------------
    # Annonce de demarrage
    # ------------------------------------------------------------------
    async def _announce(self) -> None:
        """Un seul message par lancement, et seulement si la configuration le veut."""
        if self._announced:
            return
        self._announced = True
        async with session_scope() as session:
            config = await load_config(session)
            if not config.enabled or not config.send_startup_message:
                return
            text = formatter.startup_message(
                symbols=sorted(self.state.resolved_symbols) or list(config.symbols),
                dry_run=config.dry_run,
                version=f"{STRATEGY_VERSION} / Bridge {APP_VERSION}",
                auto_trade=config.auto_trade,
            )
            result = await self._publisher.publish(session, text, config)
        if result.sent:
            logger.info("Message de demarrage publie dans le canal du watcher")
        elif result.reason:
            logger.info("Message de demarrage non publie : %s", result.reason)

    # ------------------------------------------------------------------
    # Boucles
    # ------------------------------------------------------------------
    async def _guard(self, loop: LoopState, action: Any) -> None:
        """Execute un tour sans jamais laisser une erreur tuer la boucle."""
        loop.running = True
        try:
            await action()
            loop.last_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            loop.failures += 1
            loop.last_error = str(exc)[:200]
            logger.warning("Boucle watcher %s : %s", loop.name, exc)
        finally:
            loop.runs += 1
            loop.last_run_at = utcnow()
            loop.running = False

    async def _period(self, getter: Any, default: float) -> float:
        """Periode courante, relue a chaque tour pour rester modifiable a chaud."""
        try:
            async with session_scope() as session:
                config = await load_config(session)
            return max(FLOOR_SECONDS, float(getter(config)))
        except Exception:
            return max(FLOOR_SECONDS, default)

    async def _analysis_loop(self) -> None:
        await asyncio.sleep(ANALYSIS_WARMUP)
        while True:
            await self._guard(self.state.analysis, self.run_analysis_once)
            # L'annonce vient apres le premier tour : la liste des instruments
            # reellement disponibles n'est connue qu'a ce moment-la.
            await self._guard(self.state.analysis, self._announce)
            await asyncio.sleep(
                await self._period(lambda config: config.scan_interval_seconds, 90.0)
            )

    async def _lifecycle_loop(self) -> None:
        await asyncio.sleep(LIFECYCLE_WARMUP)
        while True:
            await self._guard(self.state.lifecycle, self.run_lifecycle_once)
            await asyncio.sleep(
                await self._period(lambda config: config.lifecycle_interval_seconds, 30.0)
            )

    async def _news_loop(self) -> None:
        await asyncio.sleep(NEWS_WARMUP)
        while True:
            await self._guard(self.state.news, self.run_news_once)
            await asyncio.sleep(NEWS_EVERY_SECONDS)

    async def _maintenance_loop(self) -> None:
        await asyncio.sleep(MAINTENANCE_WARMUP)
        while True:
            await self._guard(self.state.maintenance, self.run_maintenance_once)
            await asyncio.sleep(MAINTENANCE_EVERY_SECONDS)

    # ------------------------------------------------------------------
    # Diagnostic
    # ------------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        """Etat complet du sous-systeme, sans jamais lever."""
        payload: dict[str, Any] = {
            "started": self.started,
            "state": self.state.to_dict(),
            "telegram": self._publisher.status(),
        }
        try:
            async with session_scope() as session:
                config = await load_config(session)
                payload["config"] = config.to_dict()
                payload["signals"] = await repository.stats_snapshot(session)
        except Exception as exc:
            payload["config"] = None
            payload["error"] = str(exc)
        return payload


async def journal_startup(config: WatcherConfig) -> None:
    """Trace le demarrage dans le journal du Bridge."""
    await journal.log(
        event="watcher_started",
        message=(
            f"AI Market Watcher demarre ({STRATEGY_VERSION}) sur "
            f"{len(config.symbols)} instrument(s)"
        ),
        category="system",
    )


watcher_scheduler = WatcherScheduler()

__all__ = ["LoopState", "WatcherScheduler", "WatcherState", "watcher_scheduler"]
