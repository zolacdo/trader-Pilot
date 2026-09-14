"""NewsEngine : collecte, qualification et regroupement (CDC2 sections 27 a 32).

Enchainement d'un rafraichissement :

    sources configurees -> lecture des flux -> prefiltre + IA -> deduplication
    -> verification -> enregistrement

Une source injoignable, protegee ou interdite par ``robots.txt`` n'interrompt
rien : elle est ignoree et le rapport le dit explicitement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.models.enums import EventLevel
from app.models.intelligence import NewsEvent, NewsImpact
from app.repositories import news_repo
from app.services import journal
from app.services.events import EventType, event_bus
from app.services.news.dedup import NewsDeduplicator, raw_hash, verification_for
from app.services.news.providers import (
    NewsProviderError,
    NewsSourceProtected,
    RawNewsItem,
    RobotsCache,
    RssNewsProvider,
    build_client,
)
from app.services.news.relevance import NewsRelevanceEngine, rank
from app.services.news.sources import NewsOptions, NewsSource, load_options, load_sources

logger = get_logger(__name__)


@dataclass(slots=True)
class SourceOutcome:
    """Ce qu'une source a donne lors d'une collecte."""

    key: str
    name: str
    ok: bool
    items: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "ok": self.ok,
            "items": self.items,
            "error": self.error,
        }


@dataclass(slots=True)
class CollectionReport:
    """Bilan honnete d'un rafraichissement."""

    fetched: int = 0
    created: int = 0
    duplicates: int = 0
    already_known: int = 0
    high_impact: int = 0
    sources: list[SourceOutcome] = field(default_factory=list)

    @property
    def sources_ok(self) -> int:
        return sum(1 for outcome in self.sources if outcome.ok)

    @property
    def sources_failed(self) -> list[SourceOutcome]:
        return [outcome for outcome in self.sources if not outcome.ok]

    def to_dict(self) -> dict[str, Any]:
        failed = self.sources_failed
        return {
            "fetched": self.fetched,
            "created": self.created,
            "duplicates": self.duplicates,
            "alreadyKnown": self.already_known,
            "highImpact": self.high_impact,
            "sourcesOk": self.sources_ok,
            "sourcesFailed": len(failed),
            "sources": [outcome.to_dict() for outcome in self.sources],
            "detail": self.summary(),
        }

    def summary(self) -> str:
        """Phrase affichable, sans rien embellir."""
        if not self.sources:
            return "Aucune source active : rien n'a été collecté."
        parts = [
            f"{self.fetched} dépêche(s) lue(s) sur {self.sources_ok} source(s)",
            f"{self.created} nouvelle(s)",
            f"{self.duplicates} reprise(s) regroupée(s)",
        ]
        failed = self.sources_failed
        if failed:
            names = ", ".join(outcome.name for outcome in failed[:4])
            parts.append(f"{len(failed)} source(s) ignorée(s) : {names}")
        return " ; ".join(parts) + "."


class NewsEngine:
    """Moteur d'actualites (CDC2 section 27)."""

    def __init__(
        self,
        *,
        relevance: NewsRelevanceEngine | None = None,
        deduplicator: NewsDeduplicator | None = None,
        transport: Any = None,
    ) -> None:
        self._relevance = relevance or NewsRelevanceEngine()
        self._deduplicator = deduplicator
        # ``transport`` sert aux tests : un httpx.MockTransport coupe tout acces reseau.
        self._transport = transport

    def set_transport(self, transport: Any) -> None:
        self._transport = transport

    # ------------------------------------------------------------------
    # Collecte
    # ------------------------------------------------------------------
    async def collect(
        self, sources: list[NewsSource], options: NewsOptions
    ) -> tuple[list[RawNewsItem], list[SourceOutcome]]:
        """Lit tous les flux actifs. Ne leve jamais : chaque echec est rapporte."""
        active = [source for source in sources if source.enabled]
        if not active:
            return [], []

        items: list[RawNewsItem] = []
        outcomes: list[SourceOutcome] = []
        robots = RobotsCache() if options.respect_robots else None
        async with build_client(options, transport=self._transport) as client:
            for source in active:
                provider = RssNewsProvider(source, options, client=client, robots=robots)
                try:
                    fetched = await provider.fetch()
                except NewsSourceProtected as exc:
                    outcomes.append(SourceOutcome(source.key, source.name, False, error=str(exc)))
                    logger.info("Source %s protegee : %s", source.key, exc)
                    continue
                except NewsProviderError as exc:
                    outcomes.append(SourceOutcome(source.key, source.name, False, error=str(exc)))
                    logger.info("Source %s ignoree : %s", source.key, exc)
                    continue
                except Exception as exc:
                    outcomes.append(
                        SourceOutcome(source.key, source.name, False, error=f"erreur inattendue : {exc}")
                    )
                    logger.warning("Source %s en erreur : %s", source.key, exc)
                    continue
                items.extend(fetched)
                outcomes.append(SourceOutcome(source.key, source.name, True, items=len(fetched)))
        return items, outcomes

    # ------------------------------------------------------------------
    # Rafraichissement complet
    # ------------------------------------------------------------------
    async def refresh(
        self, session: AsyncSession, *, source_keys: list[str] | None = None
    ) -> CollectionReport:
        """Collecte, qualifie et enregistre. Retourne le bilan."""
        sources = await load_sources(session)
        if source_keys:
            wanted = {key.strip() for key in source_keys if key.strip()}
            sources = [source for source in sources if source.key in wanted]
        options = await load_options(session)
        deduplicator = self._deduplicator or NewsDeduplicator(options.similarity_threshold)

        items, outcomes = await self.collect(sources, options)
        report = CollectionReport(fetched=len(items), sources=outcomes)
        if not items:
            await self._journal(session, report)
            return report

        watchlist = await news_repo.watchlist_symbols(session)
        window_start = utcnow() - timedelta(hours=options.dedup_window_hours)
        known = await news_repo.recent_news(session, window_start)

        # Empreintes deja traitees pendant ce tour, toutes sources confondues.
        seen: set[str] = set()
        for item in items:
            created = await self._ingest(
                session, item, watchlist, known, deduplicator, report, seen
            )
            if created is not None:
                known.append(created)

        await self._journal(session, report)
        return report

    async def _ingest(
        self,
        session: AsyncSession,
        item: RawNewsItem,
        watchlist: list[str],
        known: list[NewsEvent],
        deduplicator: NewsDeduplicator,
        report: CollectionReport,
        seen: set[str],
    ) -> NewsEvent | None:
        """Traite une depeche. Retourne l'enregistrement cree, s'il y en a un."""
        fingerprint = raw_hash(item.source_key, item.title, item.url)
        # La session n'est pas rincee entre deux depeches : une requete ne voit
        # donc pas ce qui vient d'etre ajoute. Sans cette memoire du tour, deux
        # exemplaires identiques dans la meme collecte violaient la contrainte
        # d'unicite et faisaient echouer tout le rafraichissement.
        if fingerprint in seen:
            report.already_known += 1
            return None
        if await news_repo.news_by_hash(session, fingerprint) is not None:
            seen.add(fingerprint)
            report.already_known += 1
            return None
        seen.add(fingerprint)

        result = await self._relevance.evaluate(item, watchlist)
        duplicate = deduplicator.find_duplicate(item.title, known, url=item.url)

        event = NewsEvent(
            raw_hash=fingerprint,
            source=item.source_name[:128],
            title=item.title,
            url=item.url,
            published_at=as_utc(item.published_at),
            received_at=item.received_at,
            summary=item.summary,
            category=result.category,
            countries=result.countries,
            entities=result.entities,
            affected_assets=result.affected_assets,
            affected_currencies=result.affected_currencies,
            impact=result.impact,
            sentiment=result.sentiment,
            confidence=result.confidence,
            reason=(result.reason or None) and result.reason[:500],
            ai_provider_used=result.ai_provider,
            ai_model_used=result.ai_model,
        )

        if duplicate is not None and duplicate.original.id is not None:
            original = duplicate.original
            event.duplicate_of = original.id
            event.confirmations = 1
            await news_repo.add_news(session, event)
            sources = await self._independent_sources(session, original)
            sources.add(event.source)
            status = verification_for(sources, official_sources=self._official(sources, item))
            await news_repo.register_confirmation(session, original, status)
            report.duplicates += 1
            return event

        event.verification = verification_for(
            {event.source}, official_sources={event.source} if item.official else set()
        )
        await news_repo.add_news(session, event)
        report.created += 1

        for symbol in result.affected_assets:
            await news_repo.link_asset(session, event.id, symbol, relevance=result.confidence)

        if rank(result.impact) >= rank(NewsImpact.HIGH):
            report.high_impact += 1
            self._publish_high_impact(event)
        return event

    @staticmethod
    async def _independent_sources(session: AsyncSession, original: NewsEvent) -> set[str]:
        sources = {original.source}
        if original.id is not None:
            for copy in await news_repo.duplicates_of(session, original.id):
                sources.add(copy.source)
        return sources

    @staticmethod
    def _official(sources: set[str], item: RawNewsItem) -> set[str]:
        return {item.source_name} & sources if item.official else set()

    @staticmethod
    def _publish_high_impact(event: NewsEvent) -> None:
        event_bus.publish(
            EventType.NEWS_HIGH_IMPACT,
            {
                "id": event.id,
                "title": event.title[:255],
                "source": event.source,
                "impact": event.impact.value,
                "sentiment": event.sentiment.value,
                "affectedAssets": list(event.affected_assets),
                "affectedCurrencies": list(event.affected_currencies),
                "verification": event.verification.value,
                "reason": event.reason,
            },
        )

    @staticmethod
    async def _journal(session: AsyncSession, report: CollectionReport) -> None:
        level = EventLevel.WARNING if report.sources_failed and not report.sources_ok else EventLevel.INFO
        await journal.record(
            session,
            event="news_refreshed",
            message=report.summary(),
            level=level,
            category="news",
            data=report.to_dict(),
        )


news_engine = NewsEngine()

__all__ = ["CollectionReport", "NewsEngine", "SourceOutcome", "news_engine"]
