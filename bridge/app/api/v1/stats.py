"""Routes statistiques, journal et onboarding."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database.session import get_session
from app.models.core import Device, utcnow
from app.models.enums import EventLevel, ExecutionMode
from app.repositories import journal_repo, settings_repo
from app.services import journal
from app.services.security.auth import require_device

router = APIRouter(tags=["statistiques"])


@router.get("/statistics")
async def statistics(
    days: int = Query(default=30, ge=1, le=365),
    execution_mode: ExecutionMode | None = Query(default=None, alias="executionMode"),
    channel_id: int | None = Query(default=None, alias="channelId"),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Statistiques globales et ventilations (CDC section 36)."""
    from app.services.statistics import service as stats

    settings = await settings_repo.get_risk_settings(session)
    mode = execution_mode or settings.execution_mode
    since = utcnow() - timedelta(days=days)

    return {
        "days": days,
        "executionMode": mode.value,
        "global": await stats.global_statistics(session, mode, since, channel_id),
        "bySymbol": await stats.by_symbol(session, mode, since),
        "byDay": await stats.by_day(session, mode, since),
        "byHour": await stats.by_hour(session, mode, since),
        "byChannel": await stats.by_channel(session, mode, since),
    }


@router.get("/statistics/today")
async def statistics_today(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    from app.services.statistics import service as stats

    return await stats.daily_summary(session)


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

@router.get("/journal")
async def list_journal(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    level: EventLevel | None = Query(default=None),
    category: str | None = Query(default=None),
    channel_id: int | None = Query(default=None, alias="channelId"),
    signal_id: int | None = Query(default=None, alias="signalId"),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    entries = await journal_repo.list_entries(
        session,
        limit=limit,
        offset=offset,
        level=level,
        category=category,
        channel_id=channel_id,
        signal_id=signal_id,
    )
    return {
        "count": len(entries),
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": entry.id,
                "createdAt": entry.created_at.isoformat(),
                "level": entry.level.value,
                "category": entry.category,
                "event": entry.event,
                "message": entry.message,
                "channelId": entry.channel_id,
                "signalId": entry.signal_id,
                "data": entry.data,
            }
            for entry in entries
        ],
    }


@router.get("/journal/audit")
async def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    signal_id: int | None = Query(default=None, alias="signalId"),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    entries = await journal_repo.list_audit(session, limit=limit, offset=offset, signal_id=signal_id)
    return {
        "count": len(entries),
        "items": [
            {
                "id": entry.id,
                "createdAt": entry.created_at.isoformat(),
                "actor": entry.actor,
                "action": entry.action,
                "target": entry.target,
                "signalId": entry.signal_id,
                "details": entry.details,
            }
            for entry in entries
        ],
    }


@router.delete("/journal")
async def purge_journal(
    keep_last: int = Query(default=5000, ge=100, le=100000, alias="keepLast"),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    removed = await journal_repo.purge_entries(session, keep_last=keep_last)
    return {"removed": removed, "keptLast": keep_last}


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

def _telegram_env_defaults() -> dict[str, Any]:
    """Identifiants Telegram lisibles dans le .env du Bridge.

    L'api_hash reste secret : on indique seulement s'il est renseigne, jamais
    sa valeur.
    """
    settings = get_settings()
    raw_id = settings.telegram_api_id.strip()
    return {
        "apiId": int(raw_id) if raw_id.isdigit() else None,
        "phone": settings.telegram_phone.strip() or None,
        "apiHashAvailable": bool(settings.telegram_api_hash.strip()),
    }


@router.get("/onboarding/state")
async def onboarding_state(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    from app.services import runtime

    state = await settings_repo.get_trading_state(session)
    summary = await runtime.connection_summary(session)
    return {
        "completed": state.onboarding_completed,
        "steps": [
            {"key": "intro", "label": "Presentation", "done": True},
            {
                "key": "bridge",
                "label": "Configuration du Bridge",
                "done": True,
                "detail": summary["bridge"].get("publicUrl") or "reseau local",
            },
            {
                "key": "metatrader",
                "label": "Verification de MetaTrader 5",
                "done": summary["mt5"].get("state") == "CONNECTED",
                "detail": summary["mt5"].get("error") or summary["mt5"].get("terminalPath") or "",
            },
            {
                "key": "telegram",
                "label": "Connexion Telegram",
                "done": bool(summary["telegram"].get("authorized")),
                # Identifiants deja presents dans bridge/.env : l'application
                # les signale pour eviter une ressaisie sur le telephone.
                # L'api_hash n'est jamais transmis, seule sa presence l'est.
                "envDefaults": _telegram_env_defaults(),
            },
            {
                "key": "openrouter",
                "label": "Configuration OpenRouter",
                "done": bool(summary["openrouter"].get("configured")),
                "detail": summary["openrouter"].get("textModel") or "",
            },
            {
                "key": "risk",
                "label": "Configuration du risque",
                "done": True,
            },
            {
                "key": "mode",
                "label": "Choix du mode (PAPER obligatoire au depart)",
                "done": True,
                "detail": summary["trading"].get("executionMode"),
            },
            {
                "key": "tests",
                "label": "Test general des connexions",
                "done": bool(summary["openrouter"].get("textModelOk"))
                and bool(summary["telegram"].get("authorized")),
            },
        ],
        "summary": {
            "telegram": summary["telegram"].get("state"),
            "openrouter": summary["openrouter"].get("state"),
            "bridge": summary["bridge"].get("state"),
            "mt5": summary["mt5"].get("state"),
            "account": summary["account"].get("kind"),
            "executionMode": summary["trading"].get("executionMode"),
            "autoTrading": summary["trading"].get("autoTradingEnabled"),
        },
    }


@router.post("/onboarding/complete")
async def complete_onboarding(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    state = await settings_repo.get_trading_state(session)
    state.onboarding_completed = True
    await settings_repo.save_trading_state(session, state)
    await journal.record(
        session, event="onboarding_completed", message="Onboarding termine", category="system"
    )
    return {"completed": True}
