"""Routes du journal de decisions, des opportunites et du shadow mode.

Le journal montre AUSSI les trades non pris, avec leur raison
(CDC2 section 76) : « 03:14 EURUSD NO TRADE — désaccord IA, actualité à fort
impact imminente ». Aucune de ces routes ne declenche d'ordre.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.core import Device, utcnow
from app.models.intelligence import (
    AiOpportunity,
    DecisionAction,
    DecisionFactor,
    DecisionRecord,
    DecisionSource,
)
from app.repositories import decision_repo
from app.services.confidence.weights import COMPONENT_LABELS, ConfidenceComponent
from app.services.decision.circuit_breaker import circuit_breaker
from app.services.decision.shadow import build_report
from app.services.security.auth import require_device

router = APIRouter(tags=["decisions"])


def _component_label(name: str) -> str | None:
    try:
        return COMPONENT_LABELS[ConfidenceComponent(name)]
    except (ValueError, KeyError):
        return None


def _decision_payload(record: DecisionRecord) -> dict[str, Any]:
    """Une ligne de journal, prise ou non prise."""
    return {
        "id": record.id,
        "createdAt": record.created_at.isoformat(),
        "symbol": record.symbol,
        "source": record.source.value,
        "action": record.action.value,
        "direction": record.direction.value if record.direction else None,
        "globalScore": record.global_score,
        "confidence": record.confidence,
        "regime": record.regime.value if record.regime else None,
        "reason": record.reason,
        "positiveFactors": list(record.positive_factors or []),
        "negativeFactors": list(record.negative_factors or []),
        "executed": record.executed,
        "shadow": record.shadow,
        "signalId": record.signal_id,
        "opportunityId": record.opportunity_id,
        "tradeId": record.trade_id,
    }


def _factor_payload(factor: DecisionFactor) -> dict[str, Any]:
    return {
        "name": factor.name,
        "label": _component_label(factor.name),
        "score": factor.score,
        "weight": factor.weight,
        "contribution": factor.contribution,
        "detail": factor.detail,
    }


def _opportunity_payload(opportunity: AiOpportunity) -> dict[str, Any]:
    return {
        "id": opportunity.id,
        "symbol": opportunity.symbol,
        "brokerSymbol": opportunity.broker_symbol,
        "createdAt": opportunity.created_at.isoformat(),
        "expiresAt": opportunity.expires_at.isoformat() if opportunity.expires_at else None,
        "direction": opportunity.direction.value,
        "strategy": opportunity.strategy,
        "entryMin": opportunity.entry_min,
        "entryMax": opportunity.entry_max,
        "entryPrice": opportunity.entry_price,
        "stopLoss": opportunity.stop_loss,
        "takeProfits": list(opportunity.take_profits or []),
        "expectedRr": opportunity.expected_rr,
        "confidence": opportunity.confidence,
        "status": opportunity.status,
        "reasons": list(opportunity.reasons or []),
        "negativeFactors": list(opportunity.negative_factors or []),
        "decisionId": opportunity.decision_id,
        "signalId": opportunity.signal_id,
    }


# ---------------------------------------------------------------------------
# Journal de decisions (CDC2 section 76)
# ---------------------------------------------------------------------------

@router.get("/decisions")
async def list_decisions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    symbol: str | None = Query(default=None),
    action: DecisionAction | None = Query(default=None),
    source: DecisionSource | None = Query(default=None),
    executed: bool | None = Query(default=None),
    not_taken: bool = Query(default=False, alias="notTaken"),
    shadow: bool | None = Query(default=None),
    days: int | None = Query(default=None, ge=1, le=365),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Journal complet, trades NON pris inclus avec leur motif.

    ``notTaken`` est le raccourci de l'application pour « montre-moi ce que le
    systeme a decide de NE PAS faire ». Il vaut ``executed=false``.
    """
    if not_taken:
        executed = False
    since = utcnow() - timedelta(days=days) if days else None
    records = await decision_repo.list_decisions(
        session,
        limit=limit,
        offset=offset,
        symbol=symbol,
        action=action,
        source=source,
        executed=executed,
        shadow=shadow,
        since=since,
    )
    total = await decision_repo.count_decisions(
        session,
        symbol=symbol,
        action=action,
        source=source,
        executed=executed,
        shadow=shadow,
        since=since,
    )
    not_taken = await decision_repo.count_decisions(
        session, symbol=symbol, source=source, executed=False, shadow=shadow, since=since
    )
    return {
        "total": total,
        "notTaken": not_taken,
        "limit": limit,
        "offset": offset,
        "items": [_decision_payload(record) for record in records],
    }


@router.get("/decisions/{decision_id}")
async def decision_detail(
    decision_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Detail d'une decision : d'ou vient chaque point du score."""
    record = await decision_repo.get_decision(session, decision_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Décision introuvable")
    factors = await decision_repo.list_factors(session, decision_id)
    payload = _decision_payload(record)
    payload["factors"] = [_factor_payload(factor) for factor in factors]
    return payload


# ---------------------------------------------------------------------------
# Opportunites generees (CDC2 sections 40 et 72)
# ---------------------------------------------------------------------------

@router.get("/opportunities")
async def list_opportunities(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    symbol: str | None = Query(default=None),
    status: str | None = Query(default=None),
    days: int | None = Query(default=None, ge=1, le=365),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days) if days else None
    opportunities = await decision_repo.list_opportunities(
        session, limit=limit, offset=offset, symbol=symbol, status=status, since=since
    )
    total = await decision_repo.count_opportunities(session, symbol=symbol, status=status)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_opportunity_payload(item) for item in opportunities],
    }


@router.get("/opportunities/{opportunity_id}")
async def opportunity_detail(
    opportunity_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    opportunity = await decision_repo.get_opportunity(session, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunité introuvable")
    payload = _opportunity_payload(opportunity)
    if opportunity.decision_id is not None:
        factors = await decision_repo.list_factors(session, opportunity.decision_id)
        payload["factors"] = [_factor_payload(factor) for factor in factors]
    else:
        payload["factors"] = []
    return payload


# ---------------------------------------------------------------------------
# Shadow mode (CDC2 sections 84 et 85)
# ---------------------------------------------------------------------------

@router.get("/shadow/performance")
async def shadow_performance(
    days: int = Query(default=30, ge=1, le=365),
    symbol: str | None = Query(default=None),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Statistiques des decisions simulees, ventilees par source et moteur."""
    since = utcnow() - timedelta(days=days)
    trades = await decision_repo.list_shadow_trades(session, since=since, symbol=symbol)
    decision_ids = [trade.decision_id for trade in trades if trade.decision_id is not None]
    labels = await decision_repo.engine_labels(session, decision_ids)

    # Deux natures de simulation, deux bilans. Le mode observation enregistre
    # quand RIEN ne part au broker ; la bande marginale enregistre ce que le
    # seuil de confiance ecarte pendant que le trading continue normalement.
    # Melangees, elles perdent leur sens : la premiere decrit un systeme a
    # l'arret, la seconde ce qu'il laisse passer en marchant. Et c'est la
    # seconde, seule, qui autorise le regleur a baisser ce seuil.
    report = build_report([item for item in trades if not item.marginal], labels)
    marginal = build_report([item for item in trades if item.marginal], labels)
    return {
        "days": days,
        "symbol": symbol,
        "disclaimer": (
            "Résultats simulés : aucun ordre n'a été envoyé. Ils ne préjugent "
            "d'aucune performance réelle."
        ),
        **report.to_dict(),
        "marginalBand": marginal.to_dict(),
    }


# ---------------------------------------------------------------------------
# Coupe-circuit (CDC2 section 86)
# ---------------------------------------------------------------------------

@router.get("/circuit-breaker")
async def circuit_breaker_state(
    _: Device = Depends(require_device),
) -> dict[str, Any]:
    """Etat du coupe-circuit et motif de suspension s'il y en a un."""
    return circuit_breaker.to_dict()


__all__ = ["router"]
