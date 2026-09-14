"""Routes de configuration : risque, OpenRouter, analyse IA, symboles, sauvegarde."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.database.session import get_session
from app.models.core import Device, RiskSettings, utcnow
from app.repositories import settings_repo
from app.schemas.requests import (
    OpenRouterKeyRequest,
    OpenRouterModelRequest,
    RiskSettingsRequest,
    SettingsImportRequest,
    SymbolMappingRequest,
)
from app.services import journal, runtime
from app.services.openrouter.chart_ai import MAX_IMAGE_BYTES
from app.services.openrouter.client import OpenRouterError
from app.services.openrouter.model_selector import FreeModelSelector
from app.services.openrouter.service import openrouter_service
from app.services.security.auth import require_device
from app.services.trading.engine import trading_engine
from app.services.trading.symbol_resolver import SymbolResolver

logger = get_logger(__name__)

router = APIRouter(tags=["configuration"])


def _risk_payload(settings: RiskSettings) -> dict[str, Any]:
    return {
        "autoTradingEnabled": settings.auto_trading_enabled,
        "executionMode": settings.execution_mode.value,
        "liveUnlocked": settings.live_unlocked,
        "riskPercent": settings.risk_percent,
        "maxDailyRiskPercent": settings.max_daily_risk_percent,
        "maxDailyLossPercent": settings.max_daily_loss_percent,
        "maxDrawdownPercent": settings.max_drawdown_percent,
        "dailyProfitTargetPercent": settings.daily_profit_target_percent,
        "dynamicRiskEnabled": settings.dynamic_risk_enabled,
        "dynamicRiskFloor": settings.dynamic_risk_floor,
        "maxLot": settings.max_lot,
        "maxPositions": settings.max_positions,
        "maxPositionsPerSymbol": settings.max_positions_per_symbol,
        "maxTotalExposureLots": settings.max_total_exposure_lots,
        "maxSpreadPoints": settings.max_spread_points,
        "maxSlippagePoints": settings.max_slippage_points,
        "maxSignalAgeSeconds": settings.max_signal_age_seconds,
        "requireStopLoss": settings.require_stop_loss,
        "requireTakeProfit": settings.require_take_profit,
        "minRiskReward": settings.min_risk_reward,
        "minConfidence": settings.min_confidence,
        "maxConsecutiveLosses": settings.max_consecutive_losses,
        "pauseAfterMaxLosses": settings.pause_after_max_losses,
        "pauseDurationMinutes": settings.pause_duration_minutes,
        "tradingHoursStart": settings.trading_hours_start,
        "tradingHoursEnd": settings.trading_hours_end,
        "tradingDays": list(settings.trading_days or []),
        "allowedSymbols": list(settings.allowed_symbols or []),
        "multiTpStrategy": settings.multi_tp_strategy.value,
        "splitRatios": list(settings.split_ratios or []),
        "breakEvenEnabled": settings.break_even_enabled,
        "breakEvenTrigger": settings.break_even_trigger.value,
        "breakEvenRMultiple": settings.break_even_r_multiple,
        "breakEvenPoints": settings.break_even_points,
        "breakEvenOffsetPoints": settings.break_even_offset_points,
        "trailingMode": settings.trailing_mode.value,
        "trailingDistancePoints": settings.trailing_distance_points,
        "trailingStepPoints": settings.trailing_step_points,
        "trailingAtrMultiple": settings.trailing_atr_multiple,
        "trailingAtrTightMultiple": settings.trailing_atr_tight_multiple,
        "trailingTightenAfterR": settings.trailing_tighten_after_r,
        "trailingAtrPeriod": settings.trailing_atr_period,
        "trailingAtrTimeframe": settings.trailing_atr_timeframe,
        "paperBalance": settings.paper_balance,
        "paperCurrency": settings.paper_currency,
        "updatedAt": settings.updated_at.isoformat(),
    }


@router.get("/risk/settings")
async def get_risk_settings(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return _risk_payload(await settings_repo.get_risk_settings(session))


@router.patch("/risk/settings")
async def update_risk_settings(
    payload: RiskSettingsRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True, by_alias=False)
    settings = await settings_repo.update_risk_settings(session, changes)
    await journal.record(
        session,
        event="risk_settings_updated",
        message=f"{len(changes)} reglage(s) de risque modifie(s)",
        category="risk",
        data={"changed": sorted(changes.keys())},
    )
    await journal.audit(
        session, action="risk_settings_updated", actor="user", details={"changed": sorted(changes.keys())}
    )
    return _risk_payload(settings)


@router.get("/risk/events")
async def list_risk_events(
    limit: int = 100,
    offset: int = 0,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    from app.repositories import trade_repo

    events = await trade_repo.list_risk_events(session, limit=limit, offset=offset)
    return [
        {
            "id": event.id,
            "createdAt": event.created_at.isoformat(),
            "signalId": event.signal_id,
            "approved": event.approved,
            "reason": event.reason.value if event.reason else None,
            "detail": event.detail,
            "checks": event.checks,
            "computedLot": event.computed_lot,
            "riskAmount": event.risk_amount,
        }
        for event in events
    ]


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------

@router.get("/openrouter/status")
async def openrouter_status(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await openrouter_service.status(session)


@router.put("/openrouter/key")
async def set_openrouter_key(
    payload: OpenRouterKeyRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Enregistre la cle chiffree. Elle n'est jamais renvoyee en clair."""
    await openrouter_service.set_api_key(session, payload.api_key)
    await journal.record(
        session,
        event="openrouter_key_updated",
        message="Cle OpenRouter enregistree" if payload.api_key else "Cle OpenRouter supprimee",
        category="ai",
    )
    if payload.api_key:
        await openrouter_service.refresh_models(session, force=True, run_tests=False)
    return await openrouter_service.status(session)


@router.get("/openrouter/models")
async def list_models(
    refresh: bool = False,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Liste les modeles GRATUITS uniquement : aucun modele payant n'est propose."""
    if refresh:
        await openrouter_service.refresh_models(session, force=True, run_tests=False)
    status = await openrouter_service.status(session)
    return {
        "autoMode": status["autoMode"],
        "textModel": status["textModel"],
        "visionModel": status["visionModel"],
        "freeModels": status["freeModels"],
        "visionModels": [model for model in status["freeModels"] if model.get("vision")],
        "note": "Seuls les modeles gratuits sont listes et selectionnables automatiquement.",
    }


@router.put("/openrouter/models")
async def set_models(
    payload: OpenRouterModelRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    selector = FreeModelSelector(openrouter_service.client, session)
    if payload.auto_mode:
        await selector.set_auto()
        await openrouter_service.refresh_models(session, force=True, run_tests=True)
    else:
        status = await openrouter_service.status(session)
        free_ids = {model.get("id") for model in status.get("freeModels", [])}
        for model in (payload.text_model, payload.vision_model):
            if model and free_ids and model not in free_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"{model} n'est pas dans la liste des modeles gratuits disponibles",
                )
        await selector.set_manual(payload.text_model, payload.vision_model)
    return await openrouter_service.status(session)


@router.post("/openrouter/test")
async def test_openrouter(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await openrouter_service.test_connection(session)


# ---------------------------------------------------------------------------
# Analyse IA de graphique
# ---------------------------------------------------------------------------

@router.post("/ai/chart")
async def analyze_chart(
    image: UploadFile = File(...),
    instrument: str | None = Form(default=None),
    question: str | None = Form(default=None),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Analyse informative d'une capture d'ecran. Ne declenche jamais d'ordre."""
    content = await image.read()
    if not content:
        raise HTTPException(status_code=400, detail="Image vide")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image trop volumineuse (maximum 4 Mo)")

    try:
        analysis = await openrouter_service.analyze_chart_image(
            session,
            content,
            image.content_type or "image/png",
            instrument=instrument,
            question=question,
        )
    except OpenRouterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await journal.record(
        session,
        event="chart_analyzed",
        message=f"Analyse IA d'un graphique ({analysis.model})",
        category="ai",
    )
    return analysis.to_dict()


# ---------------------------------------------------------------------------
# Correspondance des symboles
# ---------------------------------------------------------------------------

@router.get("/symbols/mappings")
async def list_mappings(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    mappings = await settings_repo.list_symbol_mappings(session)
    return [
        {
            "id": mapping.id,
            "alias": mapping.alias,
            "canonical": mapping.canonical,
            "brokerSymbol": mapping.broker_symbol,
            "autoDetected": mapping.auto_detected,
            "enabled": mapping.enabled,
            "updatedAt": mapping.updated_at.isoformat(),
        }
        for mapping in mappings
    ]


@router.put("/symbols/mappings")
async def upsert_mapping(
    payload: SymbolMappingRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    mapping = await settings_repo.upsert_symbol_mapping(
        session, payload.alias, payload.canonical, payload.broker_symbol, auto_detected=False
    )
    settings = await settings_repo.get_risk_settings(session)
    resolver = trading_engine.resolver_for(settings.execution_mode)
    if resolver is not None:
        resolver.invalidate()
    return {
        "id": mapping.id,
        "alias": mapping.alias,
        "canonical": mapping.canonical,
        "brokerSymbol": mapping.broker_symbol,
    }


@router.delete("/symbols/mappings/{mapping_id}")
async def delete_mapping(
    mapping_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deleted = await settings_repo.delete_symbol_mapping(session, mapping_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Correspondance inconnue")
    return {"deleted": True}


@router.get("/symbols/suggestions/{canonical}")
async def symbol_suggestions(
    canonical: str,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Propose les symboles broker correspondant reellement a l'instrument."""
    settings = await settings_repo.get_risk_settings(session)
    service = trading_engine.service_for(settings.execution_mode)
    if service is None:
        raise HTTPException(status_code=503, detail="Service de marche indisponible")
    resolver = SymbolResolver(service)
    suggestions = await resolver.suggestions(canonical)
    return {"canonical": canonical.upper(), "suggestions": suggestions}


# ---------------------------------------------------------------------------
# Sauvegarde et restauration (sans aucun secret)
# ---------------------------------------------------------------------------

@router.get("/settings/export")
async def export_settings(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Export des reglages non sensibles. Aucun secret n'est inclus."""
    settings = await settings_repo.get_risk_settings(session)
    mappings = await settings_repo.list_symbol_mappings(session)
    return {
        "exportedAt": utcnow().isoformat(),
        "version": runtime.runtime_state.to_dict()["version"],
        "risk": _risk_payload(settings),
        "symbolMappings": [
            {"alias": m.alias, "canonical": m.canonical, "brokerSymbol": m.broker_symbol}
            for m in mappings
        ],
        "note": "Cet export ne contient aucun secret (ni cle API, ni session Telegram).",
    }


@router.post("/settings/import")
async def import_settings(
    payload: SettingsImportRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Restaure des reglages exportes. Les champs sensibles sont ignores."""
    data = payload.payload or {}
    risk = data.get("risk") or {}

    # Les interrupteurs dangereux ne sont jamais restaures automatiquement.
    for forbidden in ("autoTradingEnabled", "executionMode", "liveUnlocked"):
        risk.pop(forbidden, None)

    request = RiskSettingsRequest.model_validate(risk)
    changes = request.model_dump(exclude_unset=True, by_alias=False)
    settings = await settings_repo.update_risk_settings(session, changes)

    imported_mappings = 0
    for mapping in data.get("symbolMappings") or []:
        alias = mapping.get("alias")
        canonical = mapping.get("canonical")
        if alias and canonical:
            await settings_repo.upsert_symbol_mapping(
                session, alias, canonical, mapping.get("brokerSymbol"), auto_detected=False
            )
            imported_mappings += 1

    await journal.record(
        session,
        event="settings_imported",
        message=f"{len(changes)} reglage(s) et {imported_mappings} correspondance(s) importes",
        category="system",
    )
    return {
        "importedSettings": len(changes),
        "importedMappings": imported_mappings,
        "risk": _risk_payload(settings),
        "note": "Le trading automatique et le mode d'execution ne sont jamais restaures.",
    }
