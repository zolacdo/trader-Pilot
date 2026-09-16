"""Persistance des decisions, opportunites et trades simules (CDC2).

Le journal des decisions conserve AUSSI les trades non pris, avec leur raison
(CDC2 section 76). C'est la seule facon de juger un systeme dont la bonne
reponse est souvent « ne rien faire ».
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.intelligence import (
    AIConsensusRecord,
    AiOpportunity,
    DecisionAction,
    DecisionFactor,
    DecisionRecord,
    DecisionSource,
    ShadowTrade,
)
from app.services.decision.shadow import ShadowEngine

# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

async def save_decision(
    session: AsyncSession,
    record: DecisionRecord,
    factors: Sequence[DecisionFactor] = (),
) -> DecisionRecord:
    """Enregistre une decision et sa decomposition chiffree."""
    session.add(record)
    await session.flush()
    if record.id is None:  # pragma: no cover - defense, le flush attribue l'id
        raise RuntimeError("La décision n'a pas reçu d'identifiant.")
    for factor in factors:
        factor.decision_id = record.id
        session.add(factor)
    if factors:
        await session.flush()
    return record


async def get_decision(session: AsyncSession, decision_id: int) -> DecisionRecord | None:
    return await session.get(DecisionRecord, decision_id)


def _decision_filters(
    statement,
    symbol: str | None,
    action: DecisionAction | None,
    source: DecisionSource | None,
    executed: bool | None,
    shadow: bool | None,
    since: datetime | None,
):
    if symbol is not None:
        statement = statement.where(DecisionRecord.symbol == symbol)
    if action is not None:
        statement = statement.where(DecisionRecord.action == action)
    if source is not None:
        statement = statement.where(DecisionRecord.source == source)
    if executed is not None:
        statement = statement.where(DecisionRecord.executed == executed)
    if shadow is not None:
        statement = statement.where(DecisionRecord.shadow == shadow)
    if since is not None:
        statement = statement.where(DecisionRecord.created_at >= since)
    return statement


async def list_decisions(
    session: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
    symbol: str | None = None,
    action: DecisionAction | None = None,
    source: DecisionSource | None = None,
    executed: bool | None = None,
    shadow: bool | None = None,
    since: datetime | None = None,
) -> list[DecisionRecord]:
    """Journal des decisions, trades non pris compris."""
    statement = _decision_filters(
        select(DecisionRecord), symbol, action, source, executed, shadow, since
    )
    statement = statement.order_by(DecisionRecord.created_at.desc()).offset(offset).limit(limit)
    result = await session.exec(statement)
    return list(result.all())


async def count_decisions(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    action: DecisionAction | None = None,
    source: DecisionSource | None = None,
    executed: bool | None = None,
    shadow: bool | None = None,
    since: datetime | None = None,
) -> int:
    statement = _decision_filters(
        select(func.count()).select_from(DecisionRecord),
        symbol,
        action,
        source,
        executed,
        shadow,
        since,
    )
    result = await session.exec(statement)
    return int(result.one())


async def list_factors(session: AsyncSession, decision_id: int) -> list[DecisionFactor]:
    result = await session.exec(
        select(DecisionFactor)
        .where(DecisionFactor.decision_id == decision_id)
        .order_by(DecisionFactor.contribution.desc())
    )
    return list(result.all())


async def mark_executed(
    session: AsyncSession, decision_id: int, trade_id: int | None = None
) -> DecisionRecord | None:
    """Rattache une decision au trade reellement envoye."""
    record = await session.get(DecisionRecord, decision_id)
    if record is None:
        return None
    record.executed = True
    record.trade_id = trade_id
    session.add(record)
    await session.flush()
    return record


# ---------------------------------------------------------------------------
# Opportunites
# ---------------------------------------------------------------------------

async def save_opportunity(
    session: AsyncSession, opportunity: AiOpportunity
) -> AiOpportunity:
    session.add(opportunity)
    await session.flush()
    return opportunity


async def get_opportunity(session: AsyncSession, opportunity_id: int) -> AiOpportunity | None:
    return await session.get(AiOpportunity, opportunity_id)


async def list_opportunities(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    symbol: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
) -> list[AiOpportunity]:
    statement = select(AiOpportunity)
    if symbol is not None:
        statement = statement.where(AiOpportunity.symbol == symbol)
    if status is not None:
        statement = statement.where(AiOpportunity.status == status)
    if since is not None:
        statement = statement.where(AiOpportunity.created_at >= since)
    statement = statement.order_by(AiOpportunity.created_at.desc()).offset(offset).limit(limit)
    result = await session.exec(statement)
    return list(result.all())


async def count_opportunities(
    session: AsyncSession, *, symbol: str | None = None, status: str | None = None
) -> int:
    statement = select(func.count()).select_from(AiOpportunity)
    if symbol is not None:
        statement = statement.where(AiOpportunity.symbol == symbol)
    if status is not None:
        statement = statement.where(AiOpportunity.status == status)
    result = await session.exec(statement)
    return int(result.one())


async def update_opportunity_status(
    session: AsyncSession, opportunity_id: int, status: str
) -> AiOpportunity | None:
    opportunity = await session.get(AiOpportunity, opportunity_id)
    if opportunity is None:
        return None
    opportunity.status = status
    session.add(opportunity)
    await session.flush()
    return opportunity


# ---------------------------------------------------------------------------
# Shadow mode
# ---------------------------------------------------------------------------

async def save_shadow_trade(session: AsyncSession, trade: ShadowTrade) -> ShadowTrade:
    session.add(trade)
    await session.flush()
    return trade


async def open_shadow_trades(
    session: AsyncSession, *, marginal: bool | None = None, limit: int = 500
) -> list[ShadowTrade]:
    """Simulations encore en cours, celles qui restent a mesurer.

    Une simulation sans niveaux -- un WOULD_SKIP -- est ecartee : il n'y a
    rien a suivre, et la garder dans la liste ferait demander des bougies pour
    rien a chaque tour.
    """
    statement = (
        select(ShadowTrade)
        .where(ShadowTrade.closed_at.is_(None))  # type: ignore[union-attr]
        .where(ShadowTrade.entry_price.is_not(None))  # type: ignore[union-attr]
        .where(ShadowTrade.stop_loss.is_not(None))  # type: ignore[union-attr]
    )
    if marginal is not None:
        statement = statement.where(ShadowTrade.marginal.is_(marginal))  # type: ignore[union-attr]
    statement = statement.order_by(ShadowTrade.opened_at.asc()).limit(limit)  # type: ignore[attr-defined]
    result = await session.exec(statement)
    return list(result.all())


async def list_shadow_trades(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    symbol: str | None = None,
    limit: int = 1000,
) -> list[ShadowTrade]:
    statement = select(ShadowTrade)
    if since is not None:
        statement = statement.where(ShadowTrade.opened_at >= since)
    if symbol is not None:
        statement = statement.where(ShadowTrade.symbol == symbol)
    statement = statement.order_by(ShadowTrade.opened_at.desc()).limit(limit)
    result = await session.exec(statement)
    return list(result.all())


async def engine_labels(
    session: AsyncSession, decision_ids: Sequence[int]
) -> dict[int, ShadowEngine]:
    """Retrouve quel moteur a porte chaque decision (CDC2 section 85).

    L'information vient des traces de consensus : si les deux moteurs ont
    repondu, la decision est portee par l'ensemble ; sinon par celui qui a
    repondu. Sans trace, l'origine reste inconnue — elle n'est pas devinee.
    """
    ids = [value for value in decision_ids if value is not None]
    if not ids:
        return {}

    result = await session.exec(
        select(AIConsensusRecord).where(AIConsensusRecord.decision_id.in_(ids))
    )
    labels: dict[int, ShadowEngine] = {}
    for record in result.all():
        if record.decision_id is None:
            continue
        # Deux modeles interroges = confrontation ; un seul = avis unique.
        a_primaire = record.primary_model is not None
        a_secondaire = record.secondary_model is not None
        if a_primaire and a_secondaire:
            labels[record.decision_id] = ShadowEngine.ENSEMBLE
        elif a_primaire:
            labels[record.decision_id] = ShadowEngine.OPENROUTER
    return labels


__all__ = [
    "count_decisions",
    "count_opportunities",
    "engine_labels",
    "get_decision",
    "get_opportunity",
    "list_decisions",
    "list_factors",
    "list_opportunities",
    "list_shadow_trades",
    "mark_executed",
    "save_decision",
    "save_opportunity",
    "save_shadow_trade",
    "update_opportunity_status",
]
