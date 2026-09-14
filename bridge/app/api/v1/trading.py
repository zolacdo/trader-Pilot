"""Routes de trading : MT5, positions, ordres, mode d'execution, urgence."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.database.session import get_session
from app.models.core import Device, utcnow
from app.models.enums import AccountKind, EventLevel, ExecutionMode, PositionState
from app.repositories import settings_repo, trade_repo
from app.schemas.requests import (
    BreakEvenRequest,
    ClosePositionRequest,
    EmergencyRequest,
    ExecutionModeRequest,
    LiveUnlockRequest,
    ModifyPositionRequest,
    PauseRequest,
)
from app.services import journal, runtime
from app.services.risk.calculator import round_to_step
from app.services.security.auth import require_device
from app.services.trading.engine import trading_engine
from app.services.trading.position_manager import PositionManager, break_even_price

logger = get_logger(__name__)

router = APIRouter(tags=["trading"])

# Phrases exactes exigees pour les actions irreversibles (CDC sections 10 et 32).
LIVE_CONFIRMATION_PHRASE = "JE COMPRENDS LES RISQUES"
CLOSE_ALL_CONFIRMATION_PHRASE = "FERMER TOUTES LES POSITIONS"


def _normalize(phrase: str | None) -> str:
    return " ".join((phrase or "").strip().upper().split())


async def _active_service(session: AsyncSession):
    settings = await settings_repo.get_risk_settings(session)
    service = trading_engine.service_for(settings.execution_mode)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Aucun service de marche disponible pour le mode d'execution actuel",
        )
    return settings, service


# ---------------------------------------------------------------------------
# MetaTrader 5
# ---------------------------------------------------------------------------

@router.get("/mt5/status")
async def mt5_status(_: Device = Depends(require_device)) -> dict[str, Any]:
    return await runtime.mt5_status()


@router.get("/mt5/account")
async def mt5_account(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await runtime.account_snapshot(session)


@router.post("/mt5/reconnect")
async def mt5_reconnect(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    market = trading_engine.market
    if market is None:
        raise HTTPException(status_code=503, detail="MetaTrader 5 indisponible sur ce poste")
    reconnect = getattr(market, "reconnect", None)
    try:
        connected = await reconnect() if callable(reconnect) else await market.initialize()
    except Exception as exc:
        runtime.runtime_state.mt5_error = str(exc)
        raise HTTPException(status_code=502, detail=f"Reconnexion MT5 impossible : {exc}") from exc
    trading_engine.mt5_connected = bool(connected)
    await journal.record(
        session,
        event="mt5_reconnect",
        message="Reconnexion MetaTrader demandee",
        category="mt5",
    )
    return await runtime.mt5_status()


@router.get("/mt5/symbols")
async def mt5_symbols(
    search: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=200, ge=1, le=2000),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _, service = await _active_service(session)
    names = await service.symbols()
    if search:
        needle = search.upper()
        names = [name for name in names if needle in name.upper()]
    return {"count": len(names), "symbols": names[:limit]}


@router.get("/mt5/symbols/{symbol}")
async def mt5_symbol_detail(
    symbol: str,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _, service = await _active_service(session)
    info = await service.symbol_info(symbol)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Symbole {symbol} introuvable")
    tick = await service.symbol_tick(symbol)
    return {
        **info.to_dict(),
        "tick": tick.to_dict() if tick else None,
        "spreadPoints": tick.spread_points(info.point) if tick else None,
    }


# ---------------------------------------------------------------------------
# Positions et ordres
# ---------------------------------------------------------------------------

@router.get("/positions")
async def list_positions(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    settings, service = await _active_service(session)
    live = await service.positions()
    open_records = await trade_repo.open_trades(session, settings.execution_mode)
    tracked = {trade.ticket: trade for trade in open_records}
    items = []
    for position in live:
        trade = tracked.get(position.ticket)
        items.append(
            {
                **position.to_dict(),
                "tradeId": trade.id if trade else None,
                "signalId": trade.signal_id if trade else None,
                "channelId": trade.channel_id if trade else None,
                "initialStopLoss": trade.initial_stop_loss if trade else None,
                "takeProfitTargets": list(trade.take_profit_targets or []) if trade else [],
                "tpIndex": trade.tp_index if trade else 0,
                "breakEvenApplied": trade.break_even_applied if trade else False,
                "managedByTradePilot": trade is not None,
            }
        )
    return {"executionMode": settings.execution_mode.value, "count": len(items), "items": items}


@router.get("/orders")
async def list_orders(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    settings, service = await _active_service(session)
    live = await service.orders()
    tracked = {
        order.ticket: order
        for order in await trade_repo.pending_orders(session, settings.execution_mode)
    }
    items = [
        {
            **order.to_dict(),
            "signalId": tracked[order.ticket].signal_id if order.ticket in tracked else None,
            "managedByTradePilot": order.ticket in tracked,
        }
        for order in live
    ]
    return {"executionMode": settings.execution_mode.value, "count": len(items), "items": items}


@router.get("/history")
async def trade_history(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    channel_id: int | None = Query(default=None, alias="channelId"),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings = await settings_repo.get_risk_settings(session)
    since = utcnow() - timedelta(days=days)
    trades = await trade_repo.closed_trades(
        session, settings.execution_mode, since=since, limit=limit, offset=offset, channel_id=channel_id
    )
    return {
        "count": len(trades),
        "items": [
            {
                "id": trade.id,
                "ticket": trade.ticket,
                "symbol": trade.symbol,
                "direction": trade.direction.value,
                "volume": trade.initial_volume,
                "openPrice": trade.open_price,
                "closePrice": trade.close_price,
                "stopLoss": trade.stop_loss,
                "takeProfit": trade.take_profit,
                "realizedPnl": round(trade.realized_pnl, 2),
                "rMultiple": trade.r_multiple,
                "openedAt": trade.opened_at.isoformat(),
                "closedAt": trade.closed_at.isoformat() if trade.closed_at else None,
                "closeReason": trade.close_reason,
                "channelId": trade.channel_id,
                "signalId": trade.signal_id,
                "executionMode": trade.execution_mode.value,
            }
            for trade in trades
        ],
    }


@router.post("/positions/{ticket}/modify")
async def modify_position(
    ticket: int,
    payload: ModifyPositionRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings, service = await _active_service(session)
    positions = {position.ticket: position for position in await service.positions()}
    position = positions.get(ticket)
    if position is None:
        raise HTTPException(status_code=404, detail="Position introuvable")

    stop_loss = payload.stop_loss if payload.stop_loss is not None else position.stop_loss
    take_profit = payload.take_profit if payload.take_profit is not None else position.take_profit
    result = await service.modify_position(ticket, stop_loss, take_profit)
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.message)

    trade = await trade_repo.find_by_ticket(session, ticket, settings.execution_mode)
    if trade is not None:
        trade.stop_loss = stop_loss
        trade.take_profit = take_profit
        await trade_repo.save_trade(session, trade)
    await journal.record(
        session,
        event="position_modified",
        message=f"Position #{ticket} modifiee manuellement (SL {stop_loss}, TP {take_profit})",
        category="trading",
    )
    await journal.audit(
        session,
        action="position_modified",
        actor="user",
        target=str(ticket),
        details={"stopLoss": stop_loss, "takeProfit": take_profit},
    )
    return result.to_dict()


@router.post("/positions/{ticket}/break-even")
async def move_to_break_even(
    ticket: int,
    payload: BreakEvenRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings, service = await _active_service(session)
    trade = await trade_repo.find_by_ticket(session, ticket, settings.execution_mode)
    if trade is None:
        raise HTTPException(status_code=404, detail="Position non suivie par TradePilot")
    info = await service.symbol_info(trade.symbol)
    if info is None:
        raise HTTPException(status_code=404, detail="Symbole introuvable")

    offset = payload.offset_points or settings.break_even_offset_points
    target = break_even_price(trade, info, offset)
    result = await service.modify_position(ticket, target, trade.take_profit)
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.message)
    trade.stop_loss = target
    trade.break_even_applied = True
    await trade_repo.save_trade(session, trade)
    await journal.record(
        session,
        event="break_even_applied",
        message=f"Position #{ticket} mise a break even ({target})",
        category="trading",
        signal_id=trade.signal_id,
    )
    return {"ok": True, "stopLoss": target}


@router.post("/positions/{ticket}/close")
async def close_position(
    ticket: int,
    payload: ClosePositionRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings, service = await _active_service(session)
    positions = {position.ticket: position for position in await service.positions()}
    position = positions.get(ticket)
    if position is None:
        raise HTTPException(status_code=404, detail="Position introuvable")

    volume = payload.volume
    if volume is None and payload.percentage is not None:
        info = await service.symbol_info(position.symbol)
        step = info.volume_step if info else 0.01
        volume = round_to_step(position.volume * payload.percentage / 100.0, step)
        if info is not None and volume < info.volume_min:
            volume = None  # trop petit : on ferme entierement

    result = await service.close_position(ticket, volume)
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.message)

    trade = await trade_repo.find_by_ticket(session, ticket, settings.execution_mode)
    if trade is not None:
        closed = result.volume or volume or trade.volume
        trade.closed_volume = round(trade.closed_volume + closed, 4)
        trade.volume = round(max(0.0, trade.volume - closed), 4)
        trade.close_reason = "fermeture manuelle"
        if result.price:
            trade.close_price = result.price
        if trade.volume <= 1e-9:
            trade.state = PositionState.CLOSED
            trade.closed_at = utcnow()
        else:
            trade.state = PositionState.PARTIALLY_CLOSED
        await trade_repo.save_trade(session, trade)

    await journal.record(
        session,
        event="position_closed_manually",
        message=f"Position #{ticket} fermee manuellement",
        category="trading",
    )
    await journal.audit(session, action="position_closed", actor="user", target=str(ticket))
    return result.to_dict()


@router.post("/orders/{ticket}/cancel")
async def cancel_order(
    ticket: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _, service = await _active_service(session)
    result = await service.cancel_order(ticket)
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.message)
    record = await trade_repo.find_order_by_ticket(session, ticket)
    if record is not None:
        record.state = PositionState.CANCELLED
        await trade_repo.save_order(session, record)
    await journal.record(
        session, event="order_cancelled", message=f"Ordre #{ticket} annule", category="trading"
    )
    return result.to_dict()


# ---------------------------------------------------------------------------
# Pilotage de l'automatisation
# ---------------------------------------------------------------------------

@router.get("/trading/state")
async def trading_state(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    settings = await settings_repo.get_risk_settings(session)
    state = await settings_repo.get_trading_state(session)
    return {
        "autoTradingEnabled": settings.auto_trading_enabled,
        "executionMode": settings.execution_mode.value,
        "executionModeLabel": runtime.execution_mode_label(settings.execution_mode),
        "liveUnlocked": settings.live_unlocked,
        "paused": state.paused,
        "pauseReason": state.pause_reason,
        "pausedUntil": state.paused_until.isoformat() if state.paused_until else None,
        "consecutiveLosses": state.consecutive_losses,
        "dayRealizedPnl": round(state.day_realized_pnl, 2),
        "dayRiskedPercent": round(state.day_risked_percent, 2),
    }


@router.post("/trading/auto")
async def set_auto_trading(
    enabled: bool = Query(...),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings = await settings_repo.update_risk_settings(session, {"auto_trading_enabled": enabled})
    await journal.record(
        session,
        event="auto_trading_toggled",
        message=f"Trading automatique {'active' if enabled else 'desactive'}",
        level=EventLevel.WARNING,
        category="trading",
    )
    await journal.audit(session, action="auto_trading_toggled", actor="user",
                        details={"enabled": enabled})
    return {"autoTradingEnabled": settings.auto_trading_enabled}


@router.post("/trading/pause")
async def pause_trading(
    payload: PauseRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Arrete uniquement les NOUVEAUX trades. Les positions restent ouvertes."""
    return await trading_engine.pause(session, payload.reason, payload.minutes)


@router.post("/trading/resume")
async def resume_trading(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await trading_engine.resume(session)


@router.post("/trading/execution-mode")
async def set_execution_mode(
    payload: ExecutionModeRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Change PAPER / MT5_DEMO / MT5_LIVE. Le passage en reel est verrouille."""
    settings = await settings_repo.get_risk_settings(session)

    if payload.mode is ExecutionMode.MT5_LIVE:
        if not settings.live_unlocked:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Le mode reel doit d'abord etre deverrouille depuis l'ecran dedie "
                    "(reglage explicite + phrase de confirmation)."
                ),
            )
        if _normalize(payload.confirmation) != LIVE_CONFIRMATION_PHRASE:
            raise HTTPException(
                status_code=400,
                detail=f"Saisissez exactement la phrase : {LIVE_CONFIRMATION_PHRASE}",
            )
        market = trading_engine.market
        account = await market.account_info() if market is not None else None
        if account is None:
            raise HTTPException(
                status_code=409, detail="MetaTrader 5 doit etre connecte avant de passer en reel"
            )
        if account.kind is AccountKind.UNKNOWN:
            raise HTTPException(
                status_code=409,
                detail="Impossible de determiner le type du compte MT5 : passage en reel refuse",
            )

    mode_precedent = settings.execution_mode
    updated = await settings_repo.update_risk_settings(session, {"execution_mode": payload.mode})
    if payload.mode is not mode_precedent:
        # Les comptes different : le plus haut d'equity de l'ancien mode ne
        # dit rien du nouveau (CDC section 30).
        await settings_repo.reset_account_baselines(session)
    await journal.record(
        session,
        event="execution_mode_changed",
        message=f"Mode d'execution : {runtime.execution_mode_label(payload.mode)}",
        level=EventLevel.WARNING if payload.mode is ExecutionMode.MT5_LIVE else EventLevel.INFO,
        category="trading",
    )
    await journal.audit(
        session, action="execution_mode_changed", actor="user", details={"mode": payload.mode.value}
    )
    return {
        "executionMode": updated.execution_mode.value,
        "executionModeLabel": runtime.execution_mode_label(updated.execution_mode),
    }


@router.post("/trading/live-unlock")
async def unlock_live(
    payload: LiveUnlockRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Deverrouille le mode reel. Ne l'active pas : c'est une seconde etape."""
    if not payload.acknowledged_risks:
        raise HTTPException(status_code=400, detail="Les risques doivent etre explicitement acceptes")
    if _normalize(payload.confirmation) != LIVE_CONFIRMATION_PHRASE:
        raise HTTPException(
            status_code=400, detail=f"Saisissez exactement la phrase : {LIVE_CONFIRMATION_PHRASE}"
        )

    settings = await settings_repo.get_risk_settings(session)
    settings.live_unlocked = True
    state = await settings_repo.get_trading_state(session)
    state.live_unlocked_at = utcnow()
    session.add(settings)
    await settings_repo.save_trading_state(session, state)

    await journal.record(
        session,
        event="live_unlocked",
        message="Mode reel deverrouille par l'utilisateur",
        level=EventLevel.CRITICAL,
        category="security",
    )
    await journal.audit(session, action="live_unlocked", actor="user")
    return {
        "liveUnlocked": True,
        "note": "Le mode reel est deverrouille mais pas actif. Changez le mode d'execution pour l'activer.",
    }


@router.post("/trading/live-lock")
async def lock_live(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    settings = await settings_repo.get_risk_settings(session)
    settings.live_unlocked = False
    if settings.execution_mode is ExecutionMode.MT5_LIVE:
        settings.execution_mode = ExecutionMode.MT5_DEMO
    session.add(settings)
    await journal.record(
        session,
        event="live_locked",
        message="Mode reel reverrouille",
        level=EventLevel.WARNING,
        category="security",
    )
    return {"liveUnlocked": False, "executionMode": settings.execution_mode.value}


# ---------------------------------------------------------------------------
# Urgence
# ---------------------------------------------------------------------------

@router.get("/emergency/info")
async def emergency_info(_: Device = Depends(require_device)) -> dict[str, Any]:
    return {
        "closeAllPhrase": CLOSE_ALL_CONFIRMATION_PHRASE,
        "warning": (
            "Fermer toutes les positions realise immediatement les pertes ou gains en cours. "
            "Cette action est irreversible."
        ),
    }


@router.post("/emergency/cancel-pending")
async def emergency_cancel_pending(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await trading_engine.cancel_all_pending(session)


@router.post("/emergency/close-all")
async def emergency_close_all(
    payload: EmergencyRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Ferme toutes les positions. Exige la phrase de confirmation exacte."""
    if _normalize(payload.confirmation) != CLOSE_ALL_CONFIRMATION_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=f"Saisissez exactement la phrase : {CLOSE_ALL_CONFIRMATION_PHRASE}",
        )
    return await trading_engine.close_all_positions(session, suspend=payload.suspend_automation)


@router.post("/trading/sync")
async def force_sync(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Force une reconciliation immediate avec le broker."""
    settings, service = await _active_service(session)
    manager = PositionManager(service)
    closed = await manager.sync_with_broker(session, settings.execution_mode)
    return {"closedDetected": len(closed), "executionMode": settings.execution_mode.value}
