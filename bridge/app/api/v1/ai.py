"""Routes d'intelligence hybride (CDC2 section 98).

Elles exposent l'etat des deux moteurs, la decouverte des modeles locaux, les
reglages de routage et les mesures de fiabilite. Aucune de ces routes ne
declenche un ordre.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.database.session import get_session
from app.models.core import Device
from app.models.intelligence import AIProviderKind
from app.repositories import ai_repo
from app.schemas.requests import AISettingsRequest, ProviderKeyRequest
from app.services import journal
from app.services.ai.service import ai_service
from app.services.openrouter.service import openrouter_service
from app.services.security.auth import require_device

logger = get_logger(__name__)

router = APIRouter(prefix="/ai", tags=["intelligence"])


def _settings_payload(settings) -> dict[str, Any]:
    """Reglages IA. Aucune cle ni aucun secret n'y figure."""
    return {
        "mode": settings.mode.value,
        "openRouterEnabled": settings.openrouter_enabled,
        "providers": {
            "groq": {
                "enabled": settings.groq_enabled,
                "model": settings.groq_model,
            },
            "google": {
                "enabled": settings.google_enabled,
                "model": settings.google_model,
            },
        },
        "ensemble": {
            "enabled": settings.ensemble_enabled,
            "secondaryModel": settings.ensemble_secondary_model,
            "requireConsensus": settings.require_consensus_for_auto_trade,
            "disagreementBehaviour": settings.disagreement_behaviour,
        },
        "trading": {
            "aiTradingEnabled": settings.ai_trading_enabled,
            "telegramTradingEnabled": settings.telegram_trading_enabled,
            "shadowMode": settings.shadow_mode,
            "verifySignalsWithAi": settings.verify_signals_with_ai,
            "maxAiTradesPerDay": settings.max_ai_trades_per_day,
            "maxTelegramTradesPerDay": settings.max_telegram_trades_per_day,
            "maxTradesPerSymbolPerDay": settings.max_trades_per_symbol_per_day,
            "minOpportunityConfidence": settings.min_opportunity_confidence,
        },
    }


@router.get("/status")
async def ai_status(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Etat des deux moteurs et du routeur (CDC2 section 96)."""
    settings = await ai_service.configure(session)
    status = await ai_service.status()
    last_route = await ai_repo.last_routing_event(session)
    status["settings"] = _settings_payload(settings)
    status["lastRouting"] = (
        {
            "task": last_route.task.value,
            "chosen": last_route.chosen.value if last_route.chosen else None,
            "fallbackUsed": last_route.fallback_used,
            "reason": last_route.reason,
            "at": last_route.created_at.isoformat(),
        }
        if last_route
        else None
    )
    return status


@router.get("/providers")
async def ai_providers(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await ai_service.configure(session)
    status = await ai_service.status()
    return {"providers": [status["openrouter"]], "mode": status["mode"]}


@router.put("/providers/{provider}/key")
async def set_provider_key(
    provider: str,
    payload: ProviderKeyRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Enregistre la cle chiffree d'un moteur. Elle n'est jamais renvoyee.

    Seule sa presence est exposee : c'est la meme regle que pour OpenRouter.
    """
    from app.services.security.crypto import (
        SECRET_GOOGLE_API_KEY,
        SECRET_GROQ_API_KEY,
        SecretStore,
    )

    cles = {"groq": SECRET_GROQ_API_KEY, "google": SECRET_GOOGLE_API_KEY}
    secret = cles.get(provider.strip().lower())
    if secret is None:
        raise HTTPException(
            status_code=404, detail=f"Moteur inconnu : {provider}. Attendu : groq ou google."
        )

    await SecretStore(session).set(secret, payload.api_key)
    await journal.record(
        session,
        event="provider_key_updated",
        message=(
            f"Cle {provider} enregistree" if payload.api_key else f"Cle {provider} supprimee"
        ),
        category="ai",
    )
    # Rechargement immediat : sans cela la cle ne servirait qu'au prochain
    # redemarrage, et l'utilisateur croirait qu'elle ne marche pas.
    await ai_service.configure(session)
    etat = await ai_service.status()
    return {
        "provider": provider,
        "configured": bool(payload.api_key),
        "status": etat.get("providers", {}).get(provider),
    }


@router.get("/openrouter/models")
async def openrouter_models(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Modeles gratuits OpenRouter. Aucun modele payant n'est propose."""
    status = await openrouter_service.status(session)
    return {
        "textModel": status.get("textModel"),
        "visionModel": status.get("visionModel"),
        "autoMode": status.get("autoMode"),
        "freeModels": status.get("freeModels", []),
    }


@router.post("/openrouter/test")
async def openrouter_test(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await openrouter_service.test_connection(session)


@router.get("/router/settings")
async def get_router_settings(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    settings = await ai_repo.get_settings(session)
    return _settings_payload(settings)


@router.put("/router/settings")
async def update_router_settings(
    payload: AISettingsRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Modifie le routage. Le mode reel du trading n'est jamais touche ici."""
    changes = payload.model_dump(exclude_none=True, by_alias=False)
    if not changes:
        raise HTTPException(status_code=422, detail="Aucun reglage a modifier")

    settings = await ai_repo.update_settings(session, changes)
    await ai_service.configure(session)
    await journal.record(
        session,
        event="ai_settings_updated",
        message=f"Reglages IA mis a jour : mode {settings.mode.value}",
        category="ai",
        data={"changes": sorted(changes)},
    )
    return _settings_payload(settings)


@router.get("/metrics")
async def ai_metrics(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Fiabilite mesuree de chaque moteur, par type de tache (CDC2 section 14)."""
    metrics = await ai_repo.list_metrics(session)
    return {
        "count": len(metrics),
        "items": [
            {
                "provider": metric.provider.value,
                "task": metric.task.value,
                "model": metric.model,
                "calls": metric.calls,
                "successRate": metric.success_rate,
                "validJsonRate": (
                    round(metric.valid_json / metric.calls, 3) if metric.calls else 0.0
                ),
                "averageLatencyMs": metric.average_latency_ms,
                "timeouts": metric.timeouts,
                "errors": metric.errors,
                "disagreements": metric.disagreements,
                "hallucinationsBlocked": metric.hallucinations_blocked,
                "lastError": metric.last_error,
                "lastUsedAt": metric.last_used_at.isoformat() if metric.last_used_at else None,
            }
            for metric in metrics
        ],
    }


@router.get("/consensus/{decision_id}")
async def consensus_detail(
    decision_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Confrontation des deux moteurs pour une decision donnee."""
    record = await ai_repo.get_consensus(session, decision_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Aucun consensus pour cette decision")
    return {
        "decisionId": record.decision_id,
        "task": record.task.value,
        "outcome": record.outcome.value,
        "createdAt": record.created_at.isoformat(),
        "primary": {
            "model": record.primary_model,
            "direction": (
                record.primary_direction.value if record.primary_direction else None
            ),
            "confidence": record.primary_confidence,
            "latencyMs": record.primary_latency_ms,
            "summary": record.primary_summary,
        },
        "secondary": {
            "model": record.secondary_model,
            "direction": (
                record.secondary_direction.value if record.secondary_direction else None
            ),
            "confidence": record.secondary_confidence,
            "latencyMs": record.secondary_latency_ms,
            "summary": record.secondary_summary,
        },
        "final": {
            "direction": record.final_direction.value if record.final_direction else None,
            "confidence": record.final_confidence,
            "detail": record.detail,
        },
        "note": (
            "Seules les conclusions structurees sont conservees : le raisonnement "
            "interne des modeles n'est jamais stocke."
        ),
    }


__all__ = ["AIProviderKind", "router"]
