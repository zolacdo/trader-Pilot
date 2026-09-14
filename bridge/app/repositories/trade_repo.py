"""Acces aux positions, ordres en attente et evenements de risque."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import utcnow
from app.models.enums import ExecutionMode, PositionState, RejectionReason
from app.models.trading import PendingOrderRecord, RiskEvent, TradeRecord

OPEN_STATES = (PositionState.OPEN, PositionState.PARTIALLY_CLOSED)


async def get_trade(session: AsyncSession, trade_id: int) -> TradeRecord | None:
    return await session.get(TradeRecord, trade_id)


async def find_by_ticket(
    session: AsyncSession, ticket: int, execution_mode: ExecutionMode | None = None
) -> TradeRecord | None:
    statement = select(TradeRecord).where(TradeRecord.ticket == ticket)
    if execution_mode is not None:
        statement = statement.where(TradeRecord.execution_mode == execution_mode)
    statement = statement.order_by(TradeRecord.opened_at.desc())
    result = await session.exec(statement)
    return result.first()


async def open_trades(
    session: AsyncSession,
    execution_mode: ExecutionMode | None = None,
    symbol: str | None = None,
    signal_id: int | None = None,
) -> list[TradeRecord]:
    statement = select(TradeRecord).where(TradeRecord.state.in_(OPEN_STATES))  # type: ignore[attr-defined]
    if execution_mode is not None:
        statement = statement.where(TradeRecord.execution_mode == execution_mode)
    if symbol is not None:
        statement = statement.where(TradeRecord.symbol == symbol)
    if signal_id is not None:
        statement = statement.where(TradeRecord.signal_id == signal_id)
    statement = statement.order_by(TradeRecord.opened_at.desc())
    result = await session.exec(statement)
    return list(result.all())


async def trades_for_signal(session: AsyncSession, signal_id: int) -> list[TradeRecord]:
    result = await session.exec(
        select(TradeRecord).where(TradeRecord.signal_id == signal_id).order_by(TradeRecord.opened_at)
    )
    return list(result.all())


async def closed_trades(
    session: AsyncSession,
    execution_mode: ExecutionMode | None = None,
    since: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
    channel_id: int | None = None,
) -> list[TradeRecord]:
    statement = select(TradeRecord).where(TradeRecord.state == PositionState.CLOSED)
    if execution_mode is not None:
        statement = statement.where(TradeRecord.execution_mode == execution_mode)
    if since is not None:
        statement = statement.where(TradeRecord.closed_at >= since)
    if channel_id is not None:
        statement = statement.where(TradeRecord.channel_id == channel_id)
    statement = statement.order_by(TradeRecord.closed_at.desc()).offset(offset).limit(limit)
    result = await session.exec(statement)
    return list(result.all())


async def save_trade(session: AsyncSession, trade: TradeRecord) -> TradeRecord:
    trade.updated_at = utcnow()
    session.add(trade)
    await session.flush()
    return trade


async def count_open(session: AsyncSession, execution_mode: ExecutionMode | None = None) -> int:
    statement = select(func.count()).select_from(TradeRecord).where(
        TradeRecord.state.in_(OPEN_STATES)  # type: ignore[attr-defined]
    )
    if execution_mode is not None:
        statement = statement.where(TradeRecord.execution_mode == execution_mode)
    result = await session.exec(statement)
    return int(result.one())


# ---------------------------------------------------------------------------
# Ordres en attente
# ---------------------------------------------------------------------------

async def pending_orders(
    session: AsyncSession, execution_mode: ExecutionMode | None = None, signal_id: int | None = None
) -> list[PendingOrderRecord]:
    statement = select(PendingOrderRecord).where(PendingOrderRecord.state == PositionState.PENDING)
    if execution_mode is not None:
        statement = statement.where(PendingOrderRecord.execution_mode == execution_mode)
    if signal_id is not None:
        statement = statement.where(PendingOrderRecord.signal_id == signal_id)
    statement = statement.order_by(PendingOrderRecord.created_at.desc())
    result = await session.exec(statement)
    return list(result.all())


async def find_order_by_ticket(session: AsyncSession, ticket: int) -> PendingOrderRecord | None:
    result = await session.exec(
        select(PendingOrderRecord).where(PendingOrderRecord.ticket == ticket)
    )
    return result.first()


async def save_order(session: AsyncSession, order: PendingOrderRecord) -> PendingOrderRecord:
    order.updated_at = utcnow()
    session.add(order)
    await session.flush()
    return order


# ---------------------------------------------------------------------------
# Evenements de risque
# ---------------------------------------------------------------------------

async def record_risk_event(
    session: AsyncSession,
    signal_id: int | None,
    approved: bool,
    reason: RejectionReason | None,
    detail: str,
    checks: list[dict],
    computed_lot: float | None = None,
    risk_amount: float | None = None,
) -> RiskEvent:
    event = RiskEvent(
        signal_id=signal_id,
        approved=approved,
        reason=reason,
        detail=detail[:500] if detail else None,
        checks=checks,
        computed_lot=computed_lot,
        risk_amount=risk_amount,
    )
    session.add(event)
    await session.flush()
    return event


async def list_risk_events(
    session: AsyncSession, limit: int = 100, offset: int = 0, approved: bool | None = None
) -> list[RiskEvent]:
    statement = select(RiskEvent)
    if approved is not None:
        statement = statement.where(RiskEvent.approved == approved)
    statement = statement.order_by(RiskEvent.created_at.desc()).offset(offset).limit(limit)
    result = await session.exec(statement)
    return list(result.all())
