"""Acces aux donnees du Market Watcher.

Ce module ne touche QUE les tables ``watcher_*``. C'est ce qui garantit qu'un
defaut du sous-systeme ne peut rien abimer du Bridge existant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func

# Meme convention que les autres depots du Bridge : on annote la session
# SQLAlchemy, qui est celle que FastAPI injecte, tout en appelant ``exec()``
# fourni par la sous-classe SQLModel reellement construite a l'execution.
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import as_utc, utcnow
from app.models.enums import Direction
from app.watcher.models import (
    OPEN_STATUSES,
    RiskVerdict,
    VolatilityLevel,
    WatcherAnalysis,
    WatcherDecision,
    WatcherSignal,
    WatcherSignalEvent,
    WatcherStatus,
)
from app.watcher.risk import PortfolioState

MAX_PAGE = 200


# ---------------------------------------------------------------------------
# Signaux
# ---------------------------------------------------------------------------
async def add_signal(session: AsyncSession, signal: WatcherSignal) -> WatcherSignal:
    session.add(signal)
    await session.flush()
    return signal


async def get_signal(session: AsyncSession, signal_id: int) -> WatcherSignal | None:
    return await session.get(WatcherSignal, signal_id)


async def open_signals(
    session: AsyncSession, symbol: str | None = None
) -> list[WatcherSignal]:
    """Signaux encore suivis par la boucle de cycle de vie."""
    statement = select(WatcherSignal).where(
        WatcherSignal.status.in_(tuple(OPEN_STATUSES))  # type: ignore[attr-defined]
    )
    if symbol:
        statement = statement.where(WatcherSignal.symbol == symbol.strip().upper())
    statement = statement.order_by(WatcherSignal.created_at.asc())  # type: ignore[attr-defined]
    result = await session.exec(statement)
    return list(result.all())


async def list_signals(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    direction: Direction | None = None,
    status: WatcherStatus | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WatcherSignal]:
    statement = select(WatcherSignal)
    if symbol:
        statement = statement.where(WatcherSignal.symbol == symbol.strip().upper())
    if direction is not None:
        statement = statement.where(WatcherSignal.direction == direction)
    if status is not None:
        statement = statement.where(WatcherSignal.status == status)
    if since is not None:
        statement = statement.where(WatcherSignal.created_at >= since)
    statement = (
        statement.order_by(WatcherSignal.created_at.desc())  # type: ignore[attr-defined]
        .offset(max(0, offset))
        .limit(max(1, min(limit, MAX_PAGE)))
    )
    result = await session.exec(statement)
    return list(result.all())


async def signals_since(session: AsyncSession, since: datetime) -> list[WatcherSignal]:
    """Tous les signaux crees depuis une date, clos ou non (statistiques)."""
    statement = select(WatcherSignal).where(WatcherSignal.created_at >= since)
    result = await session.exec(
        statement.order_by(WatcherSignal.created_at.asc())  # type: ignore[attr-defined]
    )
    return list(result.all())


async def count_signals_since(session: AsyncSession, since: datetime) -> int:
    result = await session.exec(
        select(func.count()).select_from(WatcherSignal).where(WatcherSignal.created_at >= since)
    )
    return int(result.one() or 0)


async def last_signal_at(session: AsyncSession, symbol: str) -> datetime | None:
    """Date du dernier signal publie sur cet instrument, quel que soit son sens."""
    result = await session.exec(
        select(WatcherSignal.created_at)
        .where(WatcherSignal.symbol == symbol.strip().upper())
        .order_by(WatcherSignal.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return as_utc(result.first())


def _start_of_day(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def portfolio_state(
    session: AsyncSession, symbol: str, direction: Direction, now: datetime | None = None
) -> PortfolioState:
    """Etat courant du watcher, tel que le Risk Manager en a besoin."""
    moment = now or utcnow()
    canonical = symbol.strip().upper()
    opened = await open_signals(session)
    same_symbol = [item for item in opened if item.symbol == canonical]
    return PortfolioState(
        active_signals=len(opened),
        signals_today=await count_signals_since(session, _start_of_day(moment)),
        active_same_symbol=len(same_symbol),
        active_same_direction=any(item.direction is direction for item in same_symbol),
        last_signal_at=await last_signal_at(session, canonical),
    )


# ---------------------------------------------------------------------------
# Evenements du cycle de vie
# ---------------------------------------------------------------------------
async def add_event(
    session: AsyncSession,
    signal_id: int,
    kind: WatcherStatus,
    price: float | None = None,
    detail: str | None = None,
    published: bool = False,
) -> WatcherSignalEvent:
    event = WatcherSignalEvent(
        signal_id=signal_id,
        kind=kind,
        price=price,
        detail=detail[:500] if detail else None,
        published=published,
    )
    session.add(event)
    await session.flush()
    return event


async def events_for(session: AsyncSession, signal_id: int) -> list[WatcherSignalEvent]:
    result = await session.exec(
        select(WatcherSignalEvent)
        .where(WatcherSignalEvent.signal_id == signal_id)
        .order_by(WatcherSignalEvent.created_at.asc())  # type: ignore[attr-defined]
    )
    return list(result.all())


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------
async def record_analysis(
    session: AsyncSession,
    *,
    symbol: str,
    decision: WatcherDecision,
    score: float,
    bias: str,
    price: float | None,
    volatility: VolatilityLevel,
    risk_verdict: RiskVerdict,
    blocked_reason: str | None = None,
    signal_id: int | None = None,
    watch_trigger: str | None = None,
    alert_sent: bool = False,
) -> WatcherAnalysis:
    analysis = WatcherAnalysis(
        symbol=symbol.strip().upper(),
        decision=decision,
        score=round(float(score), 2),
        bias=bias,
        price=price,
        volatility=volatility,
        risk_verdict=risk_verdict,
        blocked_reason=blocked_reason[:300] if blocked_reason else None,
        signal_id=signal_id,
        watch_trigger=watch_trigger[:200] if watch_trigger else None,
        alert_sent=alert_sent,
    )
    session.add(analysis)
    await session.flush()
    return analysis


async def last_analysis(session: AsyncSession, symbol: str) -> WatcherAnalysis | None:
    result = await session.exec(
        select(WatcherAnalysis)
        .where(WatcherAnalysis.symbol == symbol.strip().upper())
        .order_by(WatcherAnalysis.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return result.first()


async def latest_analyses(session: AsyncSession, limit: int = 50) -> list[WatcherAnalysis]:
    """Derniere analyse connue par instrument, la plus recente en tete."""
    result = await session.exec(
        select(WatcherAnalysis)
        .order_by(WatcherAnalysis.created_at.desc())  # type: ignore[attr-defined]
        .limit(max(1, min(limit, MAX_PAGE)) * 4)
    )
    seen: dict[str, WatcherAnalysis] = {}
    for analysis in result.all():
        seen.setdefault(analysis.symbol, analysis)
    return list(seen.values())[: max(1, min(limit, MAX_PAGE))]


async def last_watch_alert_at(session: AsyncSession, symbol: str) -> datetime | None:
    """Date de la derniere alerte WATCH reellement envoyee pour cet instrument."""
    result = await session.exec(
        select(WatcherAnalysis.created_at)
        .where(WatcherAnalysis.symbol == symbol.strip().upper())
        .where(WatcherAnalysis.alert_sent == True)
        .order_by(WatcherAnalysis.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return as_utc(result.first())


# Seules ces deux decisions ouvrent une surveillance.
_DECISIONS_DE_SURVEILLANCE = (WatcherDecision.WATCH_BUY, WatcherDecision.WATCH_SELL)


async def watch_still_open(session: AsyncSession, symbol: str) -> str | None:
    """La derniere surveillance annoncee sur cet instrument tient-elle encore ?

    Une surveillance n'est pas un evenement ponctuel : elle dit « ce marche
    approche d'un declencheur, je le suis ». Tant que le marche reste dans cet
    etat, repeter l'annonce n'apprend rien et noie le canal -- BTCUSD est reste
    en WATCH_BUY sans interruption de 05:31 a 06:07, une analyse toutes les
    90 secondes.

    La surveillance est consideree comme close des qu'une analyse posterieure
    a conclu autre chose : le marche a franchi son declencheur, ou il est
    retombe, ou il a change de sens. Rend la decision encore ouverte, sinon
    ``None``.
    """
    canonique = symbol.strip().upper()
    # ``alert_sent`` est vrai pour TOUTE publication, y compris celle d'un
    # signal. Sans ce filtre, un signal publie passait pour une surveillance
    # ouverte : le tour suivant annoncait une « surveillance levee » qui
    # n'avait jamais commence.
    result = await session.exec(
        select(WatcherAnalysis)
        .where(WatcherAnalysis.symbol == canonique)
        .where(WatcherAnalysis.alert_sent == True)
        .where(WatcherAnalysis.decision.in_(_DECISIONS_DE_SURVEILLANCE))  # type: ignore[attr-defined]
        .order_by(WatcherAnalysis.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    derniere = result.first()
    if derniere is None:
        return None

    # Une seule analyse ayant conclu autrement suffit a clore la surveillance.
    suite = await session.exec(
        select(WatcherAnalysis.id)
        .where(WatcherAnalysis.symbol == canonique)
        .where(WatcherAnalysis.created_at > derniere.created_at)
        .where(WatcherAnalysis.decision != derniere.decision)
        .limit(1)
    )
    if suite.first() is not None:
        return None
    return str(derniere.decision.value if hasattr(derniere.decision, "value") else derniere.decision)


async def purge_analyses(session: AsyncSession, older_than: datetime) -> int:
    """Efface les traces d'analyse trop anciennes pour servir a la calibration."""
    result = await session.exec(
        select(WatcherAnalysis).where(WatcherAnalysis.created_at < older_than)
    )
    rows = list(result.all())
    for row in rows:
        await session.delete(row)
    return len(rows)


async def stats_snapshot(session: AsyncSession, days: int = 30) -> dict[str, Any]:
    """Comptages bruts, utiles au diagnostic et a l'API."""
    since = utcnow() - timedelta(days=max(1, days))
    signals = await signals_since(session, since)
    opened = [item for item in signals if item.is_open]
    return {
        "windowDays": days,
        "total": len(signals),
        "open": len(opened),
        "closed": len(signals) - len(opened),
    }


__all__ = [
    "add_event",
    "add_signal",
    "count_signals_since",
    "events_for",
    "get_signal",
    "last_analysis",
    "last_signal_at",
    "last_watch_alert_at",
    "latest_analyses",
    "list_signals",
    "open_signals",
    "portfolio_state",
    "purge_analyses",
    "record_analysis",
    "signals_since",
    "stats_snapshot",
    "watch_still_open",
]
