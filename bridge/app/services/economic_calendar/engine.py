"""EconomicCalendarEngine (CDC2 sections 33 et 34).

Deux responsabilites :
 - tenir a jour les evenements economiques depuis une source configurable ;
 - preparer les rappels avant evenement, a 60, 30, 15 et 5 minutes.

Sans source configuree, ``refresh`` ne cree aucun evenement et le dit : le
calendrier vide est un fait, pas une donnee a combler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.models.enums import EventLevel
from app.models.intelligence import EconomicEvent, NewsImpact
from app.repositories import news_repo
from app.services import journal
from app.services.economic_calendar.provider import (
    CalendarProviderError,
    JsonCalendarProvider,
    build_client,
)
from app.services.economic_calendar.sources import (
    CalendarOptions,
    CalendarSource,
    load_options,
    load_sources,
)
from app.services.events import EventType, event_bus
from app.services.news.relevance import rank
from app.services.news.taxonomy import currencies_for_symbol

logger = get_logger(__name__)

NO_SOURCE_MESSAGE = (
    "Aucune source de calendrier économique n'est configurée : aucun événement n'est "
    "affiché. Ajoutez une source dans les réglages pour alimenter le calendrier."
)


@dataclass(slots=True)
class CalendarReport:
    """Bilan d'une synchronisation du calendrier."""

    fetched: int = 0
    created: int = 0
    updated: int = 0
    sources_ok: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    configured: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched": self.fetched,
            "created": self.created,
            "updated": self.updated,
            "sourcesOk": self.sources_ok,
            "errors": list(self.errors),
            "configured": self.configured,
            "detail": self.summary(),
        }

    def summary(self) -> str:
        if not self.configured:
            return NO_SOURCE_MESSAGE
        parts = [
            f"{self.fetched} événement(s) lu(s)",
            f"{self.created} ajouté(s)",
            f"{self.updated} mis à jour",
        ]
        if self.errors:
            names = ", ".join(error["source"] for error in self.errors[:4])
            parts.append(f"{len(self.errors)} source(s) ignorée(s) : {names}")
        return " ; ".join(parts) + "."


@dataclass(slots=True)
class PendingNotification:
    """Rappel a envoyer avant un evenement (CDC2 section 34)."""

    event: EconomicEvent
    offset_minutes: int
    minutes_remaining: int
    symbols: list[str]
    title: str
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "eventId": self.event.id,
            "offsetMinutes": self.offset_minutes,
            "minutesRemaining": self.minutes_remaining,
            "currency": self.event.currency,
            "impact": self.event.impact.value,
            "symbols": list(self.symbols),
            "title": self.title,
            "body": self.body,
            "scheduledAt": as_utc(self.event.scheduled_at).isoformat()
            if self.event.scheduled_at
            else None,
        }


class EconomicCalendarEngine:
    """Moteur du calendrier economique."""

    def __init__(self, *, transport: Any = None) -> None:
        # ``transport`` sert aux tests : aucun acces reseau reel.
        self._transport = transport

    def set_transport(self, transport: Any) -> None:
        self._transport = transport

    # ------------------------------------------------------------------
    # Synchronisation
    # ------------------------------------------------------------------
    async def refresh(self, session: AsyncSession) -> CalendarReport:
        sources = await load_sources(session)
        active = [source for source in sources if source.enabled]
        if not active:
            report = CalendarReport(configured=False)
            await self._journal(session, report, EventLevel.WARNING)
            return report

        options = await load_options(session)
        report = CalendarReport()
        async with build_client(options, transport=self._transport) as client:
            for source in active:
                await self._sync_source(session, source, options, client, report)
        await self._journal(session, report)
        return report

    async def _sync_source(
        self,
        session: AsyncSession,
        source: CalendarSource,
        options: CalendarOptions,
        client: Any,
        report: CalendarReport,
    ) -> None:
        provider = JsonCalendarProvider(source, options, client=client)
        try:
            rows = await provider.fetch()
        except CalendarProviderError as exc:
            report.errors.append({"source": source.name, "error": str(exc)})
            logger.info("Calendrier %s ignore : %s", source.key, exc)
            return
        except Exception as exc:
            report.errors.append({"source": source.name, "error": f"erreur inattendue : {exc}"})
            logger.warning("Calendrier %s en erreur : %s", source.key, exc)
            return

        report.sources_ok += 1
        report.fetched += len(rows)
        for row in rows:
            _, created = await news_repo.upsert_economic_event(
                session,
                external_id=row.external_id,
                scheduled_at=row.scheduled_at,
                title=row.title,
                impact=row.impact,
                country=row.country,
                currency=row.currency,
                forecast=row.forecast,
                previous=row.previous,
                actual=row.actual,
                source=source.name,
            )
            if created:
                report.created += 1
            else:
                report.updated += 1

    # ------------------------------------------------------------------
    # Consultation
    # ------------------------------------------------------------------
    @staticmethod
    def window_for(range_name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
        """Bornes UTC d'une fenetre nommee : today, tomorrow ou week."""
        moment = as_utc(now) or utcnow()
        midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        name = (range_name or "today").strip().lower()
        if name == "tomorrow":
            start = midnight + timedelta(days=1)
            return start, start + timedelta(days=1) - timedelta(microseconds=1)
        if name == "week":
            return midnight, midnight + timedelta(days=7) - timedelta(microseconds=1)
        return midnight, midnight + timedelta(days=1) - timedelta(microseconds=1)

    async def list_events(
        self,
        session: AsyncSession,
        *,
        range_name: str = "today",
        impact: NewsImpact | None = None,
        currency: str | None = None,
        now: datetime | None = None,
    ) -> tuple[list[EconomicEvent], bool]:
        """Evenements de la fenetre. Le second element dit si une source existe."""
        sources = await load_sources(session)
        configured = any(source.enabled for source in sources)
        start, end = self.window_for(range_name, now)
        events = await news_repo.list_economic_events(
            session, start=start, end=end, impact=impact, currency=currency
        )
        return events, configured

    # ------------------------------------------------------------------
    # Rappels avant evenement (CDC2 section 34)
    # ------------------------------------------------------------------
    async def due_notifications(
        self, session: AsyncSession, *, now: datetime | None = None, publish: bool = True
    ) -> list[PendingNotification]:
        """Rappels a emettre maintenant, chacun une seule fois.

        Pour un evenement donne, seule l'echeance la plus proche encore due est
        annoncee ; les echeances plus larges deja depassees sont marquees comme
        traitees pour ne jamais rattraper un retard par une rafale d'alertes.
        """
        moment = as_utc(now) or utcnow()
        options = await load_options(session)
        offsets = sorted(options.notify_offsets)
        if not offsets:
            return []

        minimum = _impact_or_default(options.notify_minimum_impact)
        horizon = moment + timedelta(minutes=offsets[-1])
        events = await news_repo.list_economic_events(session, start=moment, end=horizon)
        watchlist = await news_repo.watchlist_symbols(session)

        pending: list[PendingNotification] = []
        for event in events:
            notification = await self._notification_for(
                session, event, moment, offsets, minimum, watchlist
            )
            if notification is not None:
                pending.append(notification)
                if publish:
                    event_bus.publish(EventType.ECONOMIC_EVENT, notification.to_dict())
        return pending

    async def _notification_for(
        self,
        session: AsyncSession,
        event: EconomicEvent,
        now: datetime,
        offsets: list[int],
        minimum: NewsImpact,
        watchlist: list[str],
    ) -> PendingNotification | None:
        if rank(event.impact) < rank(minimum):
            return None
        scheduled = as_utc(event.scheduled_at)
        if scheduled is None or scheduled < now:
            return None

        remaining = int((scheduled - now).total_seconds() // 60)
        already = set(event.notified_minutes or [])
        due = [offset for offset in offsets if offset >= remaining and offset not in already]
        if not due:
            return None

        chosen = due[0]
        # Les echeances plus larges n'ont plus lieu d'etre : on les neutralise.
        await news_repo.mark_notified(session, event, [o for o in offsets if o >= remaining])
        symbols = self.affected_symbols(event.currency, watchlist)
        return PendingNotification(
            event=event,
            offset_minutes=chosen,
            minutes_remaining=max(remaining, 0),
            symbols=symbols,
            title="Événement économique important",
            body=self.format_message(event, remaining, symbols),
        )

    @staticmethod
    def affected_symbols(currency: str | None, watchlist: list[str]) -> list[str]:
        """Instruments suivis portant cette devise. Sans devise, aucun symbole."""
        code = (currency or "").strip().upper()
        if not code:
            return []
        return sorted(symbol for symbol in watchlist if code in currencies_for_symbol(symbol))

    @staticmethod
    def format_message(event: EconomicEvent, minutes_remaining: int, symbols: list[str]) -> str:
        """Message utilisateur, sur le modele du CDC2 section 34."""
        currency = event.currency or "—"
        lines = [
            f"{currency} — {event.title}",
            "",
            f"Dans {max(minutes_remaining, 0)} minutes",
            "",
            f"Impact : {event.impact.value}",
        ]
        details = [
            f"Précédent : {event.previous}" if event.previous else None,
            f"Prévision : {event.forecast}" if event.forecast else None,
        ]
        known = [detail for detail in details if detail]
        if known:
            lines.extend(["", *known])
        if symbols:
            lines.extend(["", "Positions potentiellement concernées :", *symbols])
        else:
            lines.extend(["", "Aucun instrument suivi n'est rattaché à cette devise."])
        return "\n".join(lines)

    @staticmethod
    async def _journal(
        session: AsyncSession, report: CalendarReport, level: EventLevel = EventLevel.INFO
    ) -> None:
        await journal.record(
            session,
            event="economic_calendar_refreshed",
            message=report.summary(),
            level=level,
            category="economic",
            data=report.to_dict(),
        )


def _impact_or_default(value: str) -> NewsImpact:
    try:
        return NewsImpact(value.strip().upper())
    except (AttributeError, ValueError):
        return NewsImpact.HIGH


economic_calendar_engine = EconomicCalendarEngine()

__all__ = [
    "NO_SOURCE_MESSAGE",
    "CalendarReport",
    "EconomicCalendarEngine",
    "PendingNotification",
    "economic_calendar_engine",
]
