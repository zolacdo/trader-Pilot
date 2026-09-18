"""Ordonnanceur de l'intelligence de marche (CDC2 §2, §18, §30, §34).

Sans ce fichier, tous les moteurs du CDC2 existent mais ne tournent jamais :
ils n'agissent que si quelqu'un les appelle. C'est ici que le systeme devient
reellement autonome.

Trois boucles independantes, volontairement separees : une panne des
actualites ne doit pas suspendre le scan du marche, et inversement. Chacune
survit a ses propres erreurs et reprend au tour suivant.

Les periodes sont modifiables sans redemarrage via les reglages
``intelligence.*`` : l'utilisateur peut ralentir le systeme s'il trouve qu'il
consomme trop, sans toucher au code.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.config.logging_config import get_logger
from app.database.session import session_scope
from app.models.core import utcnow
from app.models.intelligence import NewsImpact
from app.repositories import notification_repo, settings_repo
from app.services.decision import shadow_tracker
from app.services.intelligence.cycle import (
    CycleReport,
    notify_major_news,
    notify_upcoming_events,
    run_cycle,
)
from app.services.learning import tuner
from app.services.market_data.engine import MarketDataEngine
from app.services.trading import observation_tracker
from app.services.trading.engine import trading_engine

logger = get_logger(__name__)

# Periodes par defaut, en minutes. Volontairement larges : le CDC2 §2 rappelle
# que rester des heures sans rien ouvrir est normal. Scanner plus souvent
# n'ameliorerait pas les decisions, cela userait le quota et le processeur.
DEFAULT_SCAN_MINUTES = 5.0
DEFAULT_NEWS_MINUTES = 20.0
DEFAULT_CALENDAR_MINUTES = 2.0
DEFAULT_CALENDAR_SYNC_HOURS = 6.0

# Bornes de securite : une periode nulle ferait tourner une boucle a vide en
# continu, une periode demesuree reviendrait a desactiver la fonction sans le
# dire.
MIN_MINUTES = 1.0

# Une periode nulle demande une collecte en continu : le tour suivant
# part des que le precedent est fini. Le repos plancher n'existe que
# pour empecher l'emballement quand un tour echoue en une fraction de
# seconde -- sans lui, un flux injoignable ferait des centaines de
# tentatives par minute et ferait bloquer l'adresse.
CONTINUOUS_FLOOR_SECONDS = 5.0

# Au-dela de cet age, une notification n'a plus rien a signaler.
DEFAULT_RETENTION_HOURS = 4.0
MAINTENANCE_EVERY_MINUTES = 10.0
MAX_MINUTES = 24 * 60.0

SETTING_ENABLED = "intelligence.enabled"
SETTING_SCAN = "intelligence.scan_interval_minutes"
SETTING_NEWS = "intelligence.news_interval_minutes"
SETTING_CALENDAR = "intelligence.calendar_interval_minutes"
SETTING_RETENTION = "notifications.retention_hours"


@dataclass(slots=True)
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
class SchedulerState:
    scan: LoopState = field(default_factory=lambda: LoopState("scan"))
    news: LoopState = field(default_factory=lambda: LoopState("news"))
    calendar: LoopState = field(default_factory=lambda: LoopState("calendar"))
    last_report: CycleReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan": self.scan.to_dict(),
            "news": self.news.to_dict(),
            "calendar": self.calendar.to_dict(),
            "lastCycle": self.last_report.to_dict() if self.last_report else None,
        }


async def _read_minutes(key: str, default: float) -> float:
    """Periode configuree, ramenee dans des bornes raisonnables."""
    try:
        async with session_scope() as session:
            brut = await settings_repo.get_setting(session, key)
    except Exception as exc:
        logger.debug("Reglage %s illisible : %s", key, exc)
        return default
    if brut is None:
        return default
    try:
        valeur = float(str(brut).strip())
    except (TypeError, ValueError):
        logger.warning("Réglage %s ignoré : « %s » n'est pas un nombre.", key, brut)
        return default
    return max(MIN_MINUTES, min(MAX_MINUTES, valeur))


async def _read_minutes_allowing_zero(key: str, default: float) -> float:
    """Comme ``_read_minutes``, mais zero garde son sens : en continu.

    ``_read_minutes`` ramene toute valeur sous une minute a une minute. Pour
    la collecte d'actualites, l'utilisateur veut pouvoir demander « des que
    possible », ce que seul zero exprime.
    """
    try:
        async with session_scope() as session:
            brut = await settings_repo.get_setting(session, key)
    except Exception as exc:
        logger.debug("Reglage %s illisible : %s", key, exc)
        return default
    if brut is None:
        return default
    try:
        valeur = float(str(brut).strip())
    except (TypeError, ValueError):
        logger.warning("Réglage %s ignoré : « %s » n'est pas un nombre.", key, brut)
        return default
    if valeur <= 0:
        return 0.0
    return max(MIN_MINUTES, min(MAX_MINUTES, valeur))


async def _is_enabled() -> bool:
    """L'intelligence autonome peut etre coupee sans arreter le Bridge."""
    try:
        async with session_scope() as session:
            brut = await settings_repo.get_setting(session, SETTING_ENABLED)
    except Exception:
        return True
    if brut is None:
        return True
    return str(brut).strip().lower() not in {"0", "false", "non", "off"}


class IntelligenceScheduler:
    """Fait tourner les moteurs du CDC2 en arriere-plan."""

    def __init__(self) -> None:
        self.state = SchedulerState()
        self._tasks: list[asyncio.Task[None]] = []
        # Un tour a la fois par boucle. La boucle periodique et le bouton
        # « analyser maintenant » de l'application peuvent tomber en meme
        # temps : sans ce verrou, deux cycles tournaient en parallele sur les
        # memes instruments et produisaient des decisions en double.
        self._verrous: dict[str, asyncio.Lock] = {}

    def _verrou(self, nom: str) -> asyncio.Lock:
        """Verrou de la boucle, cree a la demande.

        Il ne peut pas etre cree dans ``__init__`` : l'ordonnanceur est un
        objet de module, construit avant qu'aucune boucle asyncio n'existe.
        """
        verrou = self._verrous.get(nom)
        if verrou is None:
            verrou = asyncio.Lock()
            self._verrous[nom] = verrou
        return verrou

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._scan_loop(), name="intelligence-scan"),
            asyncio.create_task(self._news_loop(), name="intelligence-news"),
            asyncio.create_task(self._calendar_loop(), name="intelligence-calendar"),
            asyncio.create_task(self._maintenance_loop(), name="intelligence-entretien"),
        ]
        logger.info(
            "Intelligence de marché démarrée (scan, actualités, calendrier, entretien)"
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
        for boucle in (self.state.scan, self.state.news, self.state.calendar):
            boucle.running = False

    @property
    def started(self) -> bool:
        return bool(self._tasks)

    # ------------------------------------------------------------------
    # Un tour de chaque boucle, isole pour pouvoir etre teste seul
    # ------------------------------------------------------------------
    async def run_scan_once(self) -> CycleReport:
        async with self._verrou("scan"), session_scope() as session:
            report = await run_cycle(session)
        self.state.last_report = report
        self.state.scan.detail = (
            f"{report.qualified} qualifiée(s) / {report.analysed} analysée(s)"
        )
        return report

    async def run_news_once(self) -> int:
        """Collecte les actualites et alerte sur celles a fort impact.

        Le bilan de collecte ne compte que des nombres ; les depeches nouvelles
        sont relues a partir de l'instant precedant la collecte. Les doublons
        eventuels sont ecartes plus loin par la deduplication des
        notifications, jamais par une supposition ici.
        """
        from app.repositories import news_repo
        from app.services.news.engine import news_engine

        debut = utcnow()
        async with self._verrou("news"), session_scope() as session:
            rapport = await news_engine.refresh(session)
            majeures = [
                event.id
                for event in await news_repo.recent_news(session, debut)
                if event.id is not None
                and event.impact in (NewsImpact.HIGH, NewsImpact.CRITICAL)
            ]
            envoyees = await notify_major_news(session, majeures) if majeures else 0
        self.state.news.detail = (
            f"{rapport.created} nouvelle(s), {envoyees} alerte(s) envoyée(s)"
        )
        return envoyees

    async def run_calendar_once(self) -> int:
        async with self._verrou("calendar"), session_scope() as session:
            envoyees = await notify_upcoming_events(session)
        self.state.calendar.detail = f"{envoyees} rappel(s) envoyé(s)"
        return envoyees

    # ------------------------------------------------------------------
    # Boucles
    # ------------------------------------------------------------------
    async def _run_guarded(self, boucle: LoopState, action: Any) -> None:
        """Execute un tour sans jamais laisser une erreur tuer la boucle."""
        boucle.running = True
        try:
            await action()
            boucle.last_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            boucle.failures += 1
            boucle.last_error = str(exc)[:200]
            logger.warning("Boucle %s : %s", boucle.name, exc)
        finally:
            boucle.runs += 1
            boucle.last_run_at = utcnow()
            boucle.running = False

    async def _scan_loop(self) -> None:
        # Premiere attente courte : laisser MetaTrader et la watchlist se
        # mettre en place avant le premier scan.
        await asyncio.sleep(60)
        while True:
            if await _is_enabled():
                await self._run_guarded(self.state.scan, self.run_scan_once)
            minutes = await _read_minutes(SETTING_SCAN, DEFAULT_SCAN_MINUTES)
            await asyncio.sleep(minutes * 60)

    async def _news_loop(self) -> None:
        await asyncio.sleep(90)
        while True:
            if await _is_enabled():
                await self._run_guarded(self.state.news, self.run_news_once)
            minutes = await _read_minutes_allowing_zero(SETTING_NEWS, DEFAULT_NEWS_MINUTES)
            # Periode nulle : le tour suivant part immediatement. Le plancher
            # ne s'applique qu'aux tours anormalement courts, donc rates.
            await asyncio.sleep(max(minutes * 60, CONTINUOUS_FLOOR_SECONDS)
                                if minutes <= 0 else minutes * 60)

    async def _calendar_loop(self) -> None:
        await asyncio.sleep(120)
        prochaine_synchro = 0.0
        while True:
            if await _is_enabled():
                # La synchronisation des evenements est bien plus lente que les
                # rappels : on la declenche a part, sinon on interrogerait la
                # source toutes les deux minutes pour rien.
                maintenant = utcnow().timestamp()
                if maintenant >= prochaine_synchro:
                    await self._run_guarded(self.state.calendar, self._sync_calendar)
                    prochaine_synchro = maintenant + DEFAULT_CALENDAR_SYNC_HOURS * 3600
                await self._run_guarded(self.state.calendar, self.run_calendar_once)
            minutes = await _read_minutes(SETTING_CALENDAR, DEFAULT_CALENDAR_MINUTES)
            await asyncio.sleep(minutes * 60)

    async def _maintenance_loop(self) -> None:
        """Efface les notifications trop vieilles pour signaler quoi que ce soit.

        Rien ne nettoyait la boite : 84 notifications s'etaient accumulees en
        dix-huit heures, dont des dizaines de depeches sans interet. La
        fonction de purge existait pourtant deja -- elle n'etait appelee par
        personne.
        """
        await asyncio.sleep(180)
        while True:
            try:
                heures = await _read_minutes(SETTING_RETENTION, DEFAULT_RETENTION_HOURS)
                async with session_scope() as session:
                    efface = await notification_repo.purge_older_than(
                        session, utcnow() - timedelta(hours=heures)
                    )
                if efface:
                    logger.info(
                        "Entretien : %s notification(s) de plus de %.0f h effacee(s)",
                        efface,
                        heures,
                    )
                # Les simulations doivent trouver une issue, sinon elles ne
                # mesurent rien : ``close_shadow_trade`` n'etait appele de
                # nulle part et 72 d'entre elles dormaient ouvertes depuis le
                # 11/09/2026.
                marche = trading_engine.market
                if marche is not None:
                    async with session_scope() as session:
                        await shadow_tracker.advance_open_trades(
                            session, MarketDataEngine(marche)
                        )
                    # Meme raison pour les canaux en mode observation : sans
                    # issue mesuree, OBSERVE etait un aller sans retour. Le
                    # canal se taisait et n'accumulait jamais la preuve
                    # permettant de le rouvrir.
                    async with session_scope() as session:
                        await observation_tracker.advance_observed_signals(
                            session, MarketDataEngine(marche)
                        )

                # Le regleur transforme les mesures d'apprentissage en
                # exigence d'entree. Il vient APRES le suivi : une simulation
                # close a l'instant doit peser sur la decision du meme tour.
                # Il ne bouge que paye d'une preuve neuve, donc passer ici
                # toutes les dix minutes ne le fait pas deriver.
                async with session_scope() as session:
                    await tuner.tune(session)
            except Exception as exc:
                # L'entretien ne doit jamais emporter les autres boucles.
                logger.warning("Entretien des notifications impossible : %s", exc)
            await asyncio.sleep(MAINTENANCE_EVERY_MINUTES * 60)

    async def _sync_calendar(self) -> None:
        from app.services.economic_calendar.engine import economic_calendar_engine

        async with session_scope() as session:
            rapport = await economic_calendar_engine.refresh(session)
        if not rapport.configured:
            # Aucune source declaree : ce n'est pas une panne, c'est un choix
            # laisse a l'utilisateur (CDC2 §33).
            logger.debug("Calendrier economique : aucune source configuree")


intelligence_scheduler = IntelligenceScheduler()

__all__ = ["IntelligenceScheduler", "LoopState", "SchedulerState", "intelligence_scheduler"]
