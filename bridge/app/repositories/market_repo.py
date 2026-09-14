"""Persistance de la watchlist, des snapshots et des regimes de marche.

Les tables sont celles definies dans ``app.models.intelligence`` : ce module
ne fait que les lire et les ecrire (CDC2 sections 17, 21 et 47).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.core import utcnow
from app.models.intelligence import (
    MarketRegime,
    MarketRegimeRecord,
    MarketSnapshot,
    Timeframe,
    WatchlistItem,
)

# Champs qu'une mise a jour partielle a le droit de modifier.
EDITABLE_FIELDS = frozenset(
    {
        "enabled",
        "scan_priority",
        "allow_ai_trading",
        "allow_telegram_trading",
        "notify_news",
        "notify_opportunities",
        "notify_volatility",
        "broker_symbol",
        "available",
    }
)


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

async def list_watchlist(session: AsyncSession, enabled_only: bool = False) -> list[WatchlistItem]:
    """Watchlist triee par priorite decroissante puis par nom."""
    statement = select(WatchlistItem)
    if enabled_only:
        statement = statement.where(WatchlistItem.enabled == True)
    statement = statement.order_by(
        col(WatchlistItem.scan_priority).desc(), col(WatchlistItem.canonical)
    )
    result = await session.exec(statement)
    return list(result.all())


async def get_watchlist_item(session: AsyncSession, canonical: str) -> WatchlistItem | None:
    result = await session.exec(
        select(WatchlistItem).where(WatchlistItem.canonical == canonical.upper())
    )
    return result.first()


async def upsert_watchlist_item(
    session: AsyncSession,
    canonical: str,
    broker_symbol: str | None,
    available: bool,
    **changes: Any,
) -> WatchlistItem:
    """Cree ou met a jour un instrument observe."""
    canonical = canonical.upper()
    item = await get_watchlist_item(session, canonical)
    if item is None:
        item = WatchlistItem(canonical=canonical)
    item.broker_symbol = broker_symbol
    item.available = available
    for key, value in changes.items():
        if key in EDITABLE_FIELDS and value is not None:
            setattr(item, key, value)
    item.updated_at = utcnow()
    session.add(item)
    await session.flush()
    return item


async def update_watchlist_item(
    session: AsyncSession, item: WatchlistItem, changes: dict[str, Any]
) -> WatchlistItem:
    for key, value in changes.items():
        if key in EDITABLE_FIELDS and value is not None:
            setattr(item, key, value)
    item.updated_at = utcnow()
    session.add(item)
    await session.flush()
    return item


async def delete_watchlist_item(session: AsyncSession, canonical: str) -> bool:
    item = await get_watchlist_item(session, canonical)
    if item is None:
        return False
    await session.delete(item)
    await session.flush()
    return True


async def mark_scanned(
    session: AsyncSession, item: WatchlistItem, moment: datetime | None = None
) -> WatchlistItem:
    item.last_scanned_at = moment or utcnow()
    session.add(item)
    await session.flush()
    return item


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

async def save_snapshot(session: AsyncSession, snapshot: MarketSnapshot) -> MarketSnapshot:
    session.add(snapshot)
    await session.flush()
    return snapshot


async def latest_snapshot(session: AsyncSession, symbol: str) -> MarketSnapshot | None:
    result = await session.exec(
        select(MarketSnapshot)
        .where(MarketSnapshot.symbol == symbol.upper())
        .order_by(col(MarketSnapshot.captured_at).desc(), col(MarketSnapshot.id).desc())
        .limit(1)
    )
    return result.first()


async def latest_snapshots(session: AsyncSession, limit: int = 50) -> list[MarketSnapshot]:
    """Dernier snapshot connu de chaque instrument, le plus recent d'abord."""
    result = await session.exec(
        select(MarketSnapshot)
        .order_by(col(MarketSnapshot.captured_at).desc(), col(MarketSnapshot.id).desc())
        .limit(max(1, int(limit)) * 20)
    )
    seen: dict[str, MarketSnapshot] = {}
    for snapshot in result.all():
        seen.setdefault(snapshot.symbol, snapshot)
        if len(seen) >= limit:
            break
    return list(seen.values())


async def list_snapshots(
    session: AsyncSession, symbol: str, limit: int = 50
) -> list[MarketSnapshot]:
    result = await session.exec(
        select(MarketSnapshot)
        .where(MarketSnapshot.symbol == symbol.upper())
        .order_by(col(MarketSnapshot.captured_at).desc(), col(MarketSnapshot.id).desc())
        .limit(max(1, int(limit)))
    )
    return list(result.all())


async def purge_snapshots(session: AsyncSession, keep_last: int = 5000) -> int:
    """Conserve les ``keep_last`` snapshots les plus recents."""
    result = await session.exec(
        select(col(MarketSnapshot.id))
        .order_by(col(MarketSnapshot.id).desc())
        .offset(max(0, int(keep_last)))
    )
    obsolete = list(result.all())
    for snapshot_id in obsolete:
        snapshot = await session.get(MarketSnapshot, snapshot_id)
        if snapshot is not None:
            await session.delete(snapshot)
    await session.flush()
    return len(obsolete)


# ---------------------------------------------------------------------------
# Regimes
# ---------------------------------------------------------------------------

async def last_regime(
    session: AsyncSession, symbol: str, timeframe: Timeframe
) -> MarketRegimeRecord | None:
    result = await session.exec(
        select(MarketRegimeRecord)
        .where(
            MarketRegimeRecord.symbol == symbol.upper(),
            MarketRegimeRecord.timeframe == timeframe,
        )
        .order_by(col(MarketRegimeRecord.detected_at).desc(), col(MarketRegimeRecord.id).desc())
        .limit(1)
    )
    return result.first()


async def record_regime_change(
    session: AsyncSession,
    symbol: str,
    timeframe: Timeframe,
    regime: MarketRegime,
    atr: float | None = None,
    atr_ratio: float | None = None,
    detail: str | None = None,
) -> MarketRegimeRecord | None:
    """Enregistre un CHANGEMENT de regime. Rend ``None`` si rien n'a change."""
    previous = await last_regime(session, symbol, timeframe)
    if previous is not None and previous.regime is regime:
        return None
    record = MarketRegimeRecord(
        symbol=symbol.upper(),
        timeframe=timeframe,
        regime=regime,
        atr=atr,
        atr_ratio=atr_ratio,
        detail=(detail or "")[:255] or None,
    )
    session.add(record)
    await session.flush()
    return record


async def list_regimes(
    session: AsyncSession, symbol: str, limit: int = 50
) -> list[MarketRegimeRecord]:
    result = await session.exec(
        select(MarketRegimeRecord)
        .where(MarketRegimeRecord.symbol == symbol.upper())
        .order_by(col(MarketRegimeRecord.detected_at).desc(), col(MarketRegimeRecord.id).desc())
        .limit(max(1, int(limit)))
    )
    return list(result.all())


__all__ = [
    "EDITABLE_FIELDS",
    "delete_watchlist_item",
    "get_watchlist_item",
    "last_regime",
    "latest_snapshot",
    "latest_snapshots",
    "list_regimes",
    "list_snapshots",
    "list_watchlist",
    "mark_scanned",
    "purge_snapshots",
    "record_regime_change",
    "save_snapshot",
    "update_watchlist_item",
    "upsert_watchlist_item",
]
