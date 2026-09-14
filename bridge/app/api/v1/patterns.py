"""Routes patterns historiques, cross-market et apprentissage (CDC2 22-26, 49).

Toutes les routes sont protegees par un jeton de peripherique. Aucune reponse
ne presente une statistique comme une recommandation : l'avertissement est
systematiquement joint.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.core import Device
from app.repositories import pattern_repo
from app.services.cross_market.analyzer import CROSS_MARKET_NOTE
from app.services.cross_market.exposure import evaluate_correlated_exposure
from app.services.historical_patterns.engine import DISCLAIMER
from app.services.historical_patterns.similarity import SIMILARITY_WARNING
from app.services.learning import performance as learning_performance
from app.services.learning.recorder import LEARNING_NOTE
from app.services.security.auth import require_device

router = APIRouter(tags=["patterns"])


def _pattern_payload(record: Any) -> dict[str, Any]:
    """Analyse persistee, rendue au format de l'application."""
    detail = record.distribution or {}
    return {
        "id": record.id,
        "symbol": record.symbol,
        "computedAt": record.computed_at.isoformat(),
        "matches": record.matches,
        "similarityMean": record.similarity_mean,
        "similarityMeanPercent": round(record.similarity_mean * 100, 1),
        "positive": record.positive,
        "negative": record.negative,
        "neutral": record.neutral,
        "horizonHours": record.horizon_hours,
        "averageMovePct": record.average_move,
        "averageMaePct": record.average_mae,
        "averageMfePct": record.average_mfe,
        "referenceFeatures": record.reference_features,
        "horizons": detail.get("horizons", []),
        "distribution": detail.get("buckets", {}),
        "analogues": detail.get("analogues", []),
        "disclaimer": record.disclaimer,
        "warning": SIMILARITY_WARNING,
    }


@router.get("/patterns/{symbol}")
async def historical_patterns(
    symbol: str,
    limit: int = Query(default=5, ge=1, le=50),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Configurations historiques comparables pour un instrument.

    Les analyses sont calculees par le moteur historique puis persistees.
    Sans analyse disponible, la reponse le dit explicitement : rien n'est
    fabrique pour remplir l'ecran.
    """
    canonical = symbol.upper()
    records = await pattern_repo.list_patterns(session, symbol=canonical, limit=limit)
    latest = records[0] if records else None
    return {
        "symbol": canonical,
        "available": latest is not None,
        "message": (
            None
            if latest is not None
            else "Aucune analyse historique disponible pour cet instrument."
        ),
        "latest": _pattern_payload(latest) if latest is not None else None,
        "history": [_pattern_payload(record) for record in records[1:]],
        "warning": SIMILARITY_WARNING,
        "disclaimer": DISCLAIMER,
    }


@router.get("/cross-market")
async def cross_market(
    max_currency_exposure: float = Query(default=2.0, gt=0, le=100, alias="maxCurrencyExposure"),
    max_correlated_exposure: float = Query(default=2.0, gt=0, le=100, alias="maxCorrelatedExposure"),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Correlations mesurees et exposition correlee agregee.

    L'exposition est calculee sur les positions reellement ouvertes, le poids
    d'une jambe etant son volume restant.
    """
    states = await pattern_repo.latest_cross_market(session)
    matrix = {state.base_symbol: dict(state.correlations) for state in states}
    legs = await pattern_repo.open_trade_legs(session)
    assessment = evaluate_correlated_exposure(
        legs,
        correlations=matrix,
        max_currency_exposure=max_currency_exposure,
        max_correlated_exposure=max_correlated_exposure,
    )
    return {
        "correlations": [
            {
                "symbol": state.base_symbol,
                "computedAt": state.computed_at.isoformat(),
                "windowDays": state.window_days,
                "timeframe": state.note,
                "values": state.correlations,
            }
            for state in states
        ],
        "available": bool(states),
        "exposure": assessment.to_dict(),
        "positions": [
            {"symbol": leg.symbol, "direction": leg.direction.value, "weight": leg.weight}
            for leg in legs
        ],
        "note": CROSS_MARKET_NOTE,
    }


@router.get("/learning/performance")
async def learning_report(
    days: int = Query(default=90, ge=1, le=730),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Performance mesuree par origine de decision et par strategie.

    Lecture seule : ces chiffres n'entrainent aucune modification automatique
    des regles du systeme.
    """
    payload = await learning_performance.overview(session, days=days)
    payload["automaticRuleUpdates"] = False
    payload["note"] = LEARNING_NOTE
    return payload
