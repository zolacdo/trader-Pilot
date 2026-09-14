"""Persistance des analyses historiques, du cross-market et des agregats.

Les tables ``historical_patterns``, ``cross_market_states`` et
``strategy_performance`` sont definies dans ``app.models.intelligence`` et ne
sont pas modifiees ici : ce module ne fait que lire et ecrire.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import utcnow
from app.models.enums import Direction, PositionState
from app.models.intelligence import (
    CrossMarketState,
    DecisionSource,
    HistoricalPattern,
    StrategyPerformance,
)
from app.models.trading import TradeRecord
from app.services.cross_market.exposure import ExposureLeg

if TYPE_CHECKING:  # pragma: no cover - uniquement pour le typage
    from app.services.cross_market.analyzer import CrossMarketReport
    from app.services.historical_patterns.engine import PatternAnalysis


# ---------------------------------------------------------------------------
# Analyses historiques
# ---------------------------------------------------------------------------

async def save_pattern(session: AsyncSession, analysis: PatternAnalysis) -> HistoricalPattern:
    """Enregistre une synthese d'analogues historiques."""
    summary = analysis.horizon_summary(analysis.horizon_hours)
    counts = analysis.counts()
    payload = analysis.to_dict(include_analogues=5)
    record = HistoricalPattern(
        symbol=analysis.symbol,
        computed_at=analysis.computed_at,
        reference_features=analysis.reference.to_dict(),
        matches=analysis.matches,
        similarity_mean=analysis.similarity_mean or 0.0,
        positive=counts.get("POSITIVE", 0),
        negative=counts.get("NEGATIVE", 0),
        neutral=counts.get("NEUTRAL", 0),
        average_move=summary["averageMovePct"],
        average_mae=summary["averageMaePct"],
        average_mfe=summary["averageMfePct"],
        horizon_hours=int(analysis.horizon_hours),
        distribution={
            "buckets": payload["distribution"],
            "horizons": payload["horizons"],
            "analogues": payload["analogues"],
            "warning": payload["warning"],
        },
    )
    session.add(record)
    await session.flush()
    return record


async def latest_pattern(session: AsyncSession, symbol: str) -> HistoricalPattern | None:
    statement = (
        select(HistoricalPattern)
        .where(HistoricalPattern.symbol == symbol)
        .order_by(HistoricalPattern.computed_at.desc())
        .limit(1)
    )
    return (await session.exec(statement)).first()


async def list_patterns(
    session: AsyncSession,
    symbol: str | None = None,
    limit: int = 20,
    since: datetime | None = None,
) -> list[HistoricalPattern]:
    statement = select(HistoricalPattern)
    if symbol is not None:
        statement = statement.where(HistoricalPattern.symbol == symbol)
    if since is not None:
        statement = statement.where(HistoricalPattern.computed_at >= since)
    statement = statement.order_by(HistoricalPattern.computed_at.desc()).limit(limit)
    return list((await session.exec(statement)).all())


# ---------------------------------------------------------------------------
# Cross-market
# ---------------------------------------------------------------------------

async def save_cross_market(
    session: AsyncSession,
    base_symbol: str,
    correlations: dict[str, float],
    window_days: int = 30,
    note: str | None = None,
    computed_at: datetime | None = None,
) -> CrossMarketState:
    record = CrossMarketState(
        base_symbol=base_symbol,
        correlations=dict(correlations),
        window_days=window_days,
        note=note,
        computed_at=computed_at or utcnow(),
    )
    session.add(record)
    await session.flush()
    return record


async def save_cross_market_report(
    session: AsyncSession, report: CrossMarketReport
) -> list[CrossMarketState]:
    """Une ligne par instrument, avec ses correlations recentes mesurees."""
    seconds_per_bar = 3600
    window_days = max(1, round(report.recent_bars * seconds_per_bar / 86400))
    saved: list[CrossMarketState] = []
    for symbol in report.symbols:
        correlations = report.recent_matrix.get(symbol, {})
        saved.append(
            await save_cross_market(
                session,
                base_symbol=symbol,
                correlations=correlations,
                window_days=window_days,
                note=report.timeframe,
                computed_at=report.computed_at,
            )
        )
    return saved


async def latest_cross_market(
    session: AsyncSession, limit: int = 50
) -> list[CrossMarketState]:
    """Dernier etat connu par instrument."""
    statement = (
        select(CrossMarketState).order_by(CrossMarketState.computed_at.desc()).limit(limit * 4)
    )
    rows = list((await session.exec(statement)).all())
    seen: dict[str, CrossMarketState] = {}
    for row in rows:
        seen.setdefault(row.base_symbol, row)
    return list(seen.values())[:limit]


# ---------------------------------------------------------------------------
# Positions ouvertes : matiere premiere de l'exposition agregee
# ---------------------------------------------------------------------------

async def open_trade_legs(session: AsyncSession) -> list[ExposureLeg]:
    """Positions encore ouvertes, ramenees a des jambes d'exposition.

    Le poids retenu est le volume restant : c'est la seule mesure de taille
    reellement disponible sur la table ``trades``.
    """
    statement = select(TradeRecord).where(
        TradeRecord.state.in_([PositionState.OPEN, PositionState.PARTIALLY_CLOSED])
    )
    trades = list((await session.exec(statement)).all())
    legs: list[ExposureLeg] = []
    for trade in trades:
        if trade.volume <= 0:
            continue
        direction = trade.direction
        if not isinstance(direction, Direction):
            direction = Direction(direction)
        legs.append(
            ExposureLeg(
                symbol=trade.symbol,
                direction=direction,
                weight=trade.volume,
                reference=str(trade.ticket),
            )
        )
    return legs


# ---------------------------------------------------------------------------
# Performance par strategie
# ---------------------------------------------------------------------------

async def get_strategy_performance(
    session: AsyncSession, day: str, strategy: str, source: DecisionSource
) -> StrategyPerformance | None:
    statement = (
        select(StrategyPerformance)
        .where(StrategyPerformance.day == day)
        .where(StrategyPerformance.strategy == strategy)
        .where(StrategyPerformance.source == source)
        .limit(1)
    )
    return (await session.exec(statement)).first()


async def upsert_strategy_performance(
    session: AsyncSession,
    day: str,
    strategy: str,
    source: DecisionSource,
    values: dict[str, Any],
) -> StrategyPerformance:
    """Ecrit ou met a jour l'agregat d'une journee pour une strategie."""
    record = await get_strategy_performance(session, day, strategy, source)
    if record is None:
        record = StrategyPerformance(day=day, strategy=strategy, source=source)
        session.add(record)
    for key, value in values.items():
        if hasattr(record, key):
            setattr(record, key, value)
    record.updated_at = utcnow()
    await session.flush()
    return record


async def list_strategy_performance(
    session: AsyncSession,
    since_day: str | None = None,
    strategy: str | None = None,
    source: DecisionSource | None = None,
    limit: int = 500,
) -> list[StrategyPerformance]:
    statement = select(StrategyPerformance)
    if since_day is not None:
        statement = statement.where(StrategyPerformance.day >= since_day)
    if strategy is not None:
        statement = statement.where(StrategyPerformance.strategy == strategy)
    if source is not None:
        statement = statement.where(StrategyPerformance.source == source)
    statement = statement.order_by(StrategyPerformance.day.desc()).limit(limit)
    return list((await session.exec(statement)).all())


__all__ = [
    "get_strategy_performance",
    "latest_cross_market",
    "latest_pattern",
    "list_patterns",
    "list_strategy_performance",
    "open_trade_legs",
    "save_cross_market",
    "save_cross_market_report",
    "save_pattern",
    "upsert_strategy_performance",
]
