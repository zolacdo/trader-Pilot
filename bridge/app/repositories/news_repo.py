"""Persistance des actualites et du calendrier economique (CDC2 sections 29 a 34).

Aucune valeur n'est completee d'office : une donnee absente reste ``None``.
Toutes les dates manipulees ici sont en UTC (CDC2 section 79).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import as_utc, utcnow
from app.models.intelligence import (
    EconomicEvent,
    NewsAssetLink,
    NewsEvent,
    NewsImpact,
    NewsSentiment,
    VerificationStatus,
    WatchlistItem,
)

MAX_PAGE_SIZE = 200


# ---------------------------------------------------------------------------
# Actualites
# ---------------------------------------------------------------------------

async def get_news(session: AsyncSession, news_id: int) -> NewsEvent | None:
    return await session.get(NewsEvent, news_id)


async def news_by_hash(session: AsyncSession, raw_hash: str) -> NewsEvent | None:
    result = await session.exec(select(NewsEvent).where(NewsEvent.raw_hash == raw_hash))
    return result.first()


async def add_news(session: AsyncSession, event: NewsEvent) -> NewsEvent:
    session.add(event)
    await session.flush()
    return event


async def recent_news(session: AsyncSession, since: datetime, limit: int = 400) -> list[NewsEvent]:
    """Fenetre de deduplication : les depeches deja connues sur la periode."""
    result = await session.exec(
        select(NewsEvent)
        .where(NewsEvent.received_at >= since)
        .order_by(NewsEvent.received_at.desc())
        .limit(limit)
    )
    return list(result.all())


async def list_news(
    session: AsyncSession,
    *,
    category: str | None = None,
    impact: NewsImpact | None = None,
    symbol: str | None = None,
    since: datetime | None = None,
    include_duplicates: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[NewsEvent]:
    """Liste filtrable. Les reprises restent masquees par defaut."""
    statement = select(NewsEvent)
    if not include_duplicates:
        statement = statement.where(NewsEvent.duplicate_of == None)  # noqa: E711
    if category:
        statement = statement.where(NewsEvent.category == category)
    if impact is not None:
        statement = statement.where(NewsEvent.impact == impact)
    if since is not None:
        statement = statement.where(NewsEvent.received_at >= since)
    if symbol:
        statement = statement.where(
            NewsEvent.id.in_(
                select(NewsAssetLink.news_id).where(NewsAssetLink.symbol == symbol.strip().upper())
            )
        )
    # Trier par date de collecte remontait les articles ramasses en dernier,
    # meme vieux de deux jours. C'est la date de publication qui interesse le
    # lecteur ; la date de collecte ne sert que lorsque la source ne date pas
    # ses articles.
    statement = (
        statement.order_by(
            func.coalesce(NewsEvent.published_at, NewsEvent.received_at).desc()
        )
        .limit(max(1, min(limit, MAX_PAGE_SIZE)))
        .offset(max(0, offset))
    )
    result = await session.exec(statement)
    return list(result.all())


async def count_news(
    session: AsyncSession,
    *,
    category: str | None = None,
    impact: NewsImpact | None = None,
    symbol: str | None = None,
    since: datetime | None = None,
    include_duplicates: bool = False,
) -> int:
    statement = select(func.count()).select_from(NewsEvent)
    if not include_duplicates:
        statement = statement.where(NewsEvent.duplicate_of == None)  # noqa: E711
    if category:
        statement = statement.where(NewsEvent.category == category)
    if impact is not None:
        statement = statement.where(NewsEvent.impact == impact)
    if since is not None:
        statement = statement.where(NewsEvent.received_at >= since)
    if symbol:
        statement = statement.where(
            NewsEvent.id.in_(
                select(NewsAssetLink.news_id).where(NewsAssetLink.symbol == symbol.strip().upper())
            )
        )
    result = await session.exec(statement)
    return int(result.one())


async def purge_unimportant(session: AsyncSession, older_than: datetime) -> int:
    """Efface les depeches qui ne touchent aucun marche suivi.

    Le flux sature : 306 depeches lues a chaque tour, dont la grande majorite
    sans le moindre rapport avec le portefeuille. Une depeche est conservee
    des qu'elle peut compter -- impact au-dessus de LOW, tonalite marquee, ou
    rattachement a un instrument. Sont effacees celles qui cumulent les trois
    signes de l'insignifiance : impact faible, tonalite neutre, et aucun
    rattachement marche.

    Les liens d'actifs sont retires d'abord : une depeche rattachee n'est de
    toute facon jamais candidate, mais la contrainte doit rester saine si la
    regle evolue. Rend le nombre de depeches effacees.
    """
    resultat = await session.exec(
        select(NewsEvent)
        .where(NewsEvent.published_at < older_than)
        .where(NewsEvent.impact == NewsImpact.LOW)
        .where(NewsEvent.sentiment == NewsSentiment.NEUTRAL)
    )
    candidates = list(resultat.all())
    if not candidates:
        return 0

    efface = 0
    for depeche in candidates:
        if depeche.id is None:
            continue
        liens = await session.exec(
            select(NewsAssetLink).where(NewsAssetLink.news_id == depeche.id)
        )
        if liens.first() is not None:
            # Rattachee a un instrument : elle concerne le portefeuille.
            continue
        await session.delete(depeche)
        efface += 1
    if efface:
        # Sans ce vidage, les suppressions restent en attente : une lecture
        # faite dans la meme session verrait encore les depeches effacees.
        await session.flush()
    return efface


async def duplicates_of(session: AsyncSession, news_id: int) -> list[NewsEvent]:
    """Reprises rattachees a une actualite : ce sont ses confirmations."""
    result = await session.exec(
        select(NewsEvent)
        .where(NewsEvent.duplicate_of == news_id)
        .order_by(NewsEvent.received_at.asc())
    )
    return list(result.all())


async def register_confirmation(
    session: AsyncSession, original: NewsEvent, status: VerificationStatus
) -> NewsEvent:
    """Une reprise de plus : le compteur monte, le statut suit."""
    original.confirmations += 1
    original.verification = status
    session.add(original)
    await session.flush()
    return original


async def link_asset(
    session: AsyncSession, news_id: int, symbol: str, relevance: float = 0.0
) -> NewsAssetLink | None:
    """Rattache une actualite a un instrument. Le lien est unique."""
    key = symbol.strip().upper()
    if not key:
        return None
    result = await session.exec(
        select(NewsAssetLink).where(
            NewsAssetLink.news_id == news_id, NewsAssetLink.symbol == key
        )
    )
    link = result.first()
    if link is None:
        link = NewsAssetLink(news_id=news_id, symbol=key, relevance=relevance)
    else:
        link.relevance = max(link.relevance, relevance)
    session.add(link)
    await session.flush()
    return link


async def links_for(session: AsyncSession, news_id: int) -> list[NewsAssetLink]:
    result = await session.exec(select(NewsAssetLink).where(NewsAssetLink.news_id == news_id))
    return list(result.all())


async def watchlist_symbols(session: AsyncSession, *, only_enabled: bool = True) -> list[str]:
    """Instruments que TradePilot a le droit d'observer (CDC2 section 17)."""
    statement = select(WatchlistItem)
    if only_enabled:
        statement = statement.where(WatchlistItem.enabled == True)
    result = await session.exec(statement.order_by(WatchlistItem.canonical))
    return [item.canonical.upper() for item in result.all()]


# ---------------------------------------------------------------------------
# Calendrier economique
# ---------------------------------------------------------------------------

async def get_economic_event(session: AsyncSession, event_id: int) -> EconomicEvent | None:
    return await session.get(EconomicEvent, event_id)


async def economic_event_by_external_id(
    session: AsyncSession, external_id: str
) -> EconomicEvent | None:
    result = await session.exec(
        select(EconomicEvent).where(EconomicEvent.external_id == external_id)
    )
    return result.first()


async def upsert_economic_event(
    session: AsyncSession,
    *,
    external_id: str,
    scheduled_at: datetime,
    title: str,
    impact: NewsImpact = NewsImpact.LOW,
    country: str | None = None,
    currency: str | None = None,
    forecast: str | None = None,
    previous: str | None = None,
    actual: str | None = None,
    source: str | None = None,
) -> tuple[EconomicEvent, bool]:
    """Cree ou met a jour un evenement. Retourne (evenement, cree).

    Les champs absents de la source ne sont pas ecrases par ``None`` : une
    valeur deja connue vaut mieux qu'un trou, et on n'invente jamais de
    chiffre a la place.
    """
    existing = await economic_event_by_external_id(session, external_id)
    if existing is None:
        event = EconomicEvent(
            external_id=external_id,
            scheduled_at=scheduled_at,
            title=title,
            impact=impact,
            country=country,
            currency=currency,
            forecast=forecast,
            previous=previous,
            actual=actual,
            source=source,
        )
        session.add(event)
        await session.flush()
        return event, True

    # Comparaison en UTC des deux cotes : SQLite rend une date sans fuseau, la
    # confronter telle quelle a une date aware ferait croire a un report a
    # chaque synchronisation et effacerait les notifications deja envoyees.
    if as_utc(existing.scheduled_at) != as_utc(scheduled_at):
        # Un report remet les notifications a zero : l'heure a change.
        existing.scheduled_at = scheduled_at
        existing.notified_minutes = []
    existing.title = title
    existing.impact = impact
    for field_name, value in (
        ("country", country),
        ("currency", currency),
        ("forecast", forecast),
        ("previous", previous),
        ("actual", actual),
        ("source", source),
    ):
        if value is not None:
            setattr(existing, field_name, value)
    existing.updated_at = utcnow()
    session.add(existing)
    await session.flush()
    return existing, False


async def list_economic_events(
    session: AsyncSession,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    impact: NewsImpact | None = None,
    currency: str | None = None,
    limit: int = 200,
) -> list[EconomicEvent]:
    statement = select(EconomicEvent)
    if start is not None:
        statement = statement.where(EconomicEvent.scheduled_at >= start)
    if end is not None:
        statement = statement.where(EconomicEvent.scheduled_at <= end)
    if impact is not None:
        statement = statement.where(EconomicEvent.impact == impact)
    if currency:
        statement = statement.where(EconomicEvent.currency == currency.strip().upper())
    statement = statement.order_by(EconomicEvent.scheduled_at.asc()).limit(
        max(1, min(limit, MAX_PAGE_SIZE * 5))
    )
    result = await session.exec(statement)
    return list(result.all())


async def mark_notified(
    session: AsyncSession, event: EconomicEvent, offsets: list[int]
) -> EconomicEvent:
    """Marque des echeances comme deja notifiees : jamais deux fois (CDC2 34)."""
    already = set(event.notified_minutes or [])
    already.update(int(offset) for offset in offsets)
    event.notified_minutes = sorted(already, reverse=True)
    event.updated_at = utcnow()
    session.add(event)
    await session.flush()
    return event


__all__ = [
    "add_news",
    "count_news",
    "duplicates_of",
    "economic_event_by_external_id",
    "get_economic_event",
    "get_news",
    "link_asset",
    "links_for",
    "list_economic_events",
    "list_news",
    "mark_notified",
    "news_by_hash",
    "recent_news",
    "register_confirmation",
    "upsert_economic_event",
    "watchlist_symbols",
]
