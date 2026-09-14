"""Routes systeme : sante, appairage, tableau de bord, diagnostic."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.config.settings import API_VERSION, APP_VERSION
from app.database.session import get_session
from app.models.core import Device, utcnow
from app.models.enums import ExecutionMode, SignalStatus
from app.repositories import journal_repo, settings_repo, signal_repo, trade_repo
from app.schemas.requests import DeviceActionRequest, PairingRequest, PushTokenRequest
from app.services import journal, runtime
from app.services.events import event_bus
from app.services.openrouter.service import openrouter_service
from app.services.security.auth import (
    PAIRING_TTL_MINUTES,
    AuthService,
    client_is_local,
    pairing_manager,
    require_device,
)
from app.services.trading.engine import trading_engine
from app.services.tunnel.ngrok_service import ngrok_service

logger = get_logger(__name__)

router = APIRouter(tags=["systeme"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Sonde publique : ne revele aucune donnee de compte."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "apiVersion": API_VERSION,
        "uptimeSeconds": runtime.runtime_state.uptime_seconds,
    }


# ---------------------------------------------------------------------------
# Appairage
# ---------------------------------------------------------------------------

@router.get("/pairing/status")
async def pairing_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Indique si un code est actif. Le code lui-meme n'est jamais renvoye."""
    current = pairing_manager.current
    return {
        "pairingOpen": current is not None,
        "expiresInSeconds": current.seconds_remaining if current else 0,
        "hasPairedDevice": await AuthService(session).has_any_device(),
    }


@router.post("/pairing/renew", status_code=status.HTTP_201_CREATED)
async def renew_pairing_code(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Genere un nouveau code d'appairage, depuis la machine du Bridge seulement.

    Un code est valable 15 minutes et ne sert qu'une fois. Sans cette route, il
    faudrait redemarrer le Bridge pour appairer un nouveau telephone : penible
    lorsqu'il tourne en permanence au demarrage de la machine.

    L'appel est refuse a distance : il faut un acces au PC, ce qui est
    exactement le niveau de confiance requis pour autoriser un appareil.
    """
    if not client_is_local(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Un code d'appairage ne peut etre demande que depuis la machine du Bridge. "
                "Ouvrez une console sur ce PC, ou consultez bridge/data/logs/bridge-stdout.log."
            ),
        )

    code = pairing_manager.issue()
    await journal.record(
        session,
        event="pairing_code_renewed",
        message="Nouveau code d'appairage genere depuis la machine locale",
        category="security",
    )
    logger.info("Nouveau code d'appairage : %s (valable %s min)", code.code, PAIRING_TTL_MINUTES)
    return {
        "code": code.code,
        "expiresInSeconds": code.seconds_remaining,
        "publicUrl": ngrok_service.status.public_url,
    }


@router.post("/pairing", status_code=status.HTTP_201_CREATED)
async def pair_device(
    payload: PairingRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Echange le code affiche par le Bridge contre un jeton de peripherique."""
    if not pairing_manager.consume(payload.code):
        await journal.record(
            session,
            event="pairing_failed",
            message="Code d'appairage invalide ou expire",
            category="security",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Code d'appairage invalide ou expire"
        )

    device, token = await AuthService(session).register_device(
        payload.device_id, payload.name, payload.platform
    )
    await journal.record(
        session,
        event="device_paired",
        message=f"Appareil appaire : {device.name}",
        category="security",
    )
    await journal.audit(session, action="device_paired", actor="user", target=device.device_id)
    return {
        "deviceId": device.device_id,
        "token": token,
        "bridgeVersion": APP_VERSION,
        "publicUrl": ngrok_service.status.public_url,
    }


@router.get("/devices")
async def list_devices(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    devices = await AuthService(session).list_devices()
    return [
        {
            "deviceId": device.device_id,
            "name": device.name,
            "platform": device.platform,
            "createdAt": device.created_at.isoformat(),
            "lastSeenAt": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "revoked": device.revoked,
        }
        for device in devices
    ]


@router.post("/devices/revoke")
async def revoke_device(
    payload: DeviceActionRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    revoked = await AuthService(session).revoke(payload.device_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Appareil inconnu")
    await journal.audit(session, action="device_revoked", actor="user", target=payload.device_id)
    return {"revoked": True}


@router.post("/devices/rotate")
async def rotate_device_token(
    payload: DeviceActionRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    token = await AuthService(session).rotate(payload.device_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Appareil inconnu")
    await journal.audit(session, action="device_token_rotated", actor="user", target=payload.device_id)
    return {"token": token}


@router.post("/devices/push-token")
async def register_push_token(
    payload: PushTokenRequest,
    device: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    device.push_token = payload.token
    session.add(device)
    return {"registered": True}


# ---------------------------------------------------------------------------
# Etat et tableau de bord
# ---------------------------------------------------------------------------

@router.get("/status")
async def full_status(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await runtime.connection_summary(session)


@router.get("/dashboard")
async def dashboard(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Donnees de l'ecran d'accueil (CDC section 31)."""
    summary = await runtime.connection_summary(session)
    settings = await settings_repo.get_risk_settings(session)
    state = await settings_repo.get_trading_state(session)
    mode = settings.execution_mode

    open_trades = await trade_repo.open_trades(session, mode)
    pending = await trade_repo.pending_orders(session, mode)
    recent_signals = await signal_repo.list_signals(session, limit=10)
    recent_events = await journal_repo.list_entries(session, limit=15)

    account = summary.get("account", {}).get("account") or {}
    start_balance = state.day_start_balance or account.get("balance") or 0.0
    equity = account.get("equity") or 0.0
    drawdown = 0.0
    if state.peak_equity and state.peak_equity > 0:
        drawdown = max(0.0, (state.peak_equity - equity) / state.peak_equity * 100)

    floating = sum(trade.profit for trade in open_trades)
    realized = state.day_realized_pnl

    return {
        **summary,
        "metrics": {
            "balance": account.get("balance"),
            "equity": account.get("equity"),
            "margin": account.get("margin"),
            "marginFree": account.get("marginFree"),
            "currency": account.get("currency"),
            "dayStartBalance": start_balance,
            "profitToday": round(realized, 2) if realized > 0 else 0.0,
            "lossToday": round(realized, 2) if realized < 0 else 0.0,
            "realizedToday": round(realized, 2),
            "floatingPnl": round(floating, 2),
            "drawdownPercent": round(drawdown, 2),
            "dayRiskedPercent": round(state.day_risked_percent, 2),
        },
        "openPositions": [
            {
                "id": trade.id,
                "ticket": trade.ticket,
                "symbol": trade.symbol,
                "direction": trade.direction.value,
                "volume": trade.volume,
                "openPrice": trade.open_price,
                "stopLoss": trade.stop_loss,
                "takeProfit": trade.take_profit,
                "profit": round(trade.profit, 2),
                "openedAt": trade.opened_at.isoformat(),
                "channelId": trade.channel_id,
                "signalId": trade.signal_id,
            }
            for trade in open_trades
        ],
        "pendingOrders": [
            {
                "id": order.id,
                "ticket": order.ticket,
                "symbol": order.symbol,
                "orderType": order.order_type.value,
                "volume": order.volume,
                "price": order.price,
                "stopLoss": order.stop_loss,
                "takeProfit": order.take_profit,
                "createdAt": order.created_at.isoformat(),
            }
            for order in pending
        ],
        "recentSignals": [_signal_summary(signal) for signal in recent_signals],
        "recentEvents": [
            {
                "id": entry.id,
                "createdAt": entry.created_at.isoformat(),
                "level": entry.level.value,
                "event": entry.event,
                "message": entry.message,
            }
            for entry in recent_events
        ],
    }


def _signal_summary(signal: Any) -> dict[str, Any]:
    return {
        "id": signal.id,
        "channelId": signal.channel_id,
        "symbol": signal.normalized_symbol or signal.symbol,
        "direction": signal.direction.value if signal.direction else None,
        "orderType": signal.order_type.value if signal.order_type else None,
        "entryPrice": signal.entry_price,
        "entryMin": signal.entry_min,
        "entryMax": signal.entry_max,
        "stopLoss": signal.stop_loss,
        "takeProfits": list(signal.take_profits or []),
        "confidence": signal.confidence,
        "status": signal.status.value,
        "rejectionReason": signal.rejection_reason.value if signal.rejection_reason else None,
        "receivedAt": signal.received_at.isoformat(),
        "parserSource": signal.parser_source.value,
    }


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------

def _algo_trading_check(mt5_summary: dict[str, Any]) -> dict[str, Any]:
    """Verifie l'interrupteur « Trading algorithmique » du terminal.

    Il est independant de l'autorisation du compte. Tant qu'il est ferme,
    MetaTrader refuse tous les ordres envoyes par un programme — et le refus
    arrive sous forme de code technique, apres coup. Le signaler ici evite de
    presenter un systeme entierement vert qui ne peut rien executer.
    """
    terminal = mt5_summary.get("terminal") or {}
    allowed = terminal.get("tradeAllowed")
    if mt5_summary.get("state") != "CONNECTED" or allowed is None:
        return {
            "key": "mt5_algo_trading",
            "label": "Trading algorithmique (terminal)",
            "ok": True,
            "detail": "Etat non mesurable tant que le terminal n'est pas connecte.",
        }
    return {
        "key": "mt5_algo_trading",
        "label": "Trading algorithmique (terminal)",
        "ok": bool(allowed),
        "detail": (
            "Autorise dans MetaTrader 5."
            if allowed
            else "Desactive dans MetaTrader 5 : aucun ordre automatique ne peut partir. "
            "Ouvrez le terminal, menu Outils > Options > Expert Advisors, "
            "et cochez « Autoriser le trading algorithmique »."
        ),
    }


@router.get("/diagnostics")
async def diagnostics(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Ecran Diagnostic systeme (CDC section 60).

    Aucun bouton de ce diagnostic n'envoie d'ordre reel : les tests
    d'execution passent uniquement par le simulateur ou un compte demo.
    """
    summary = await runtime.connection_summary(session)
    settings = await settings_repo.get_risk_settings(session)

    last_signals = await signal_repo.list_signals(session, limit=1)
    last_trades = await trade_repo.closed_trades(session, limit=1)
    open_count = await trade_repo.count_open(session)

    checks: list[dict[str, Any]] = [
        {"key": "bridge", "label": "Bridge", "ok": True, "detail": f"version {APP_VERSION}"},
        {
            "key": "database",
            "label": "Base de donnees",
            "ok": True,
            "detail": str(runtime.describe_environment()["dataDir"]),
        },
        {
            "key": "telegram",
            "label": "Telegram",
            "ok": bool(summary["telegram"].get("authorized")),
            "detail": summary["telegram"].get("lastError") or summary["telegram"].get("state", ""),
        },
        {
            "key": "mt5",
            "label": "MetaTrader 5",
            "ok": summary["mt5"].get("state") == "CONNECTED",
            "detail": summary["mt5"].get("error") or summary["mt5"].get("terminalPath") or "",
        },
        _algo_trading_check(summary["mt5"]),
        {
            "key": "openrouter",
            "label": "OpenRouter",
            "ok": bool(summary["openrouter"].get("textModelOk")),
            "detail": summary["openrouter"].get("lastError")
            or (summary["openrouter"].get("textModel") or "aucun modele"),
        },
        {
            "key": "websocket",
            "label": "WebSocket",
            "ok": True,
            "detail": f"{event_bus.subscriber_count} client(s) connecte(s)",
        },
        {
            "key": "tunnel",
            "label": "Acces distant (ngrok)",
            "ok": (not ngrok_service.status.enabled) or ngrok_service.status.running,
            "detail": ngrok_service.status.public_url or ngrok_service.status.error or "desactive",
        },
    ]

    warnings: list[str] = []
    if not runtime.runtime_state.mt5_real_tested and settings.execution_mode is not ExecutionMode.PAPER:
        warnings.append(
            "MT5 REAL NOT TESTED ON THIS MACHINE : l'integration MetaTrader n'a pas encore ete "
            "validee par une connexion reelle depuis ce poste."
        )
    if summary["account"].get("kind") == "UNKNOWN" and settings.execution_mode is not ExecutionMode.PAPER:
        warnings.append(
            "Impossible de determiner si le compte MT5 est demo ou reel : l'execution automatique "
            "sera refusee par securite."
        )
    paper_live = summary["account"].get("paperUsesLivePrices")
    if settings.execution_mode is ExecutionMode.PAPER and paper_live is False:
        warnings.append(
            "Le paper trading utilise des prix simules : MetaTrader 5 n'est pas connecte."
        )

    return {
        "checks": checks,
        "warnings": warnings,
        "environment": runtime.describe_environment(),
        "runtime": runtime.runtime_state.to_dict(),
        "executionMode": settings.execution_mode.value,
        "executionModeLabel": runtime.execution_mode_label(settings.execution_mode),
        "accountKind": summary["account"].get("kind"),
        "openPositions": open_count,
        "lastSignal": _signal_summary(last_signals[0]) if last_signals else None,
        "lastTrade": (
            {
                "ticket": last_trades[0].ticket,
                "symbol": last_trades[0].symbol,
                "profit": round(last_trades[0].realized_pnl, 2),
                "closedAt": last_trades[0].closed_at.isoformat() if last_trades[0].closed_at else None,
            }
            if last_trades
            else None
        ),
    }


@router.post("/diagnostics/test/{target}")
async def run_diagnostic_test(
    target: str,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Tests unitaires de connexion. Aucun n'envoie d'ordre reel."""
    if target == "openrouter":
        return await openrouter_service.test_connection(session)

    if target == "telegram":
        telegram = await runtime.telegram_status()
        return {
            "ok": bool(telegram.get("authorized")),
            "detail": telegram.get("lastError") or telegram.get("state"),
        }

    if target == "mt5":
        market = trading_engine.market
        if market is None:
            return {"ok": False, "detail": "MetaTrader 5 indisponible sur ce poste"}
        connected = await market.is_connected()
        account = await market.account_info() if connected else None
        return {
            "ok": connected,
            "detail": runtime.runtime_state.mt5_error or ("connecte" if connected else "non connecte"),
            "account": account.to_dict() if account else None,
        }

    if target == "websocket":
        event_bus.publish("diagnostic.ping", {"message": "Test WebSocket"})
        return {"ok": True, "subscribers": event_bus.subscriber_count}

    if target == "notification":
        event_bus.publish(
            "notification",
            {"title": "Test de notification", "body": "Le Bridge peut vous notifier."},
        )
        return {"ok": True, "detail": "Notification de test envoyee"}

    if target == "tunnel":
        tunnel = await ngrok_service.refresh()
        return {"ok": tunnel.running or not tunnel.enabled, **tunnel.to_dict()}

    raise HTTPException(status_code=404, detail=f"Test inconnu : {target}")


@router.get("/diagnostics/export")
async def export_diagnostics(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Export texte pour le support. Les secrets sont deja masques a la source."""
    entries = await journal_repo.list_entries(session, limit=500)
    summary = await runtime.connection_summary(session)
    signals = await signal_repo.list_signals(session, limit=50)
    return {
        "generatedAt": utcnow().isoformat(),
        "runtime": runtime.runtime_state.to_dict(),
        "environment": runtime.describe_environment(),
        "status": summary,
        "recentSignals": [_signal_summary(signal) for signal in signals],
        "journal": [
            {
                "createdAt": entry.created_at.isoformat(),
                "level": entry.level.value,
                "event": entry.event,
                "message": entry.message,
            }
            for entry in entries
        ],
    }


@router.get("/go-live-checklist")
async def go_live_checklist(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Criteres a verifier avant d'envisager le mode reel (CDC section 68)."""
    settings = await settings_repo.get_risk_settings(session)
    summary = await runtime.connection_summary(session)
    since = utcnow() - timedelta(days=30)

    signals_count = await signal_repo.count_signals(session, since=since)
    demo_trades = await trade_repo.closed_trades(session, ExecutionMode.MT5_DEMO, since=since, limit=500)
    paper_trades = await trade_repo.closed_trades(session, ExecutionMode.PAPER, since=since, limit=500)
    executed = await signal_repo.list_signals(
        session,
        limit=200,
        statuses=[SignalStatus.OPEN, SignalStatus.CLOSED, SignalStatus.SENT],
        since=since,
    )
    break_even_trades = [trade for trade in demo_trades + paper_trades if trade.break_even_applied]
    duplicates = await signal_repo.count_duplicate_messages(session)

    items = [
        {
            "key": "mt5_demo_connected",
            "label": "MT5 connecte sur un compte demo",
            "done": summary["mt5"].get("state") == "CONNECTED"
            and summary["account"].get("kind") == "DEMO",
        },
        {
            "key": "telegram_connected",
            "label": "Telegram connecte",
            "done": bool(summary["telegram"].get("authorized")),
        },
        {
            "key": "signals_received",
            "label": "Au moins 20 signaux recus et analyses",
            "done": signals_count >= 20,
            "detail": f"{signals_count} signaux sur 30 jours",
        },
        {
            "key": "signals_executed",
            "label": "Au moins 10 signaux executes en paper ou demo",
            "done": len(executed) >= 10,
            "detail": f"{len(executed)} executions",
        },
        {
            # Verification reelle : aucun message Telegram ne doit avoir produit
            # deux signaux distincts. Ce n'est pas un point acquis d'avance.
            "key": "no_duplicates",
            "label": "Aucun message n'a produit deux signaux",
            "done": duplicates == 0,
            "detail": (
                "Aucun doublon detecte sur l'ensemble des messages recus"
                if duplicates == 0
                else f"{duplicates} message(s) ont produit plusieurs signaux : a investiguer"
            ),
        },
        {
            "key": "trades_closed",
            "label": "Des trades ont ete fermes correctement",
            "done": len(demo_trades) + len(paper_trades) >= 5,
            "detail": f"{len(demo_trades) + len(paper_trades)} trades fermes",
        },
        {
            "key": "break_even_tested",
            "label": "Break even declenche au moins une fois",
            "done": len(break_even_trades) >= 1,
        },
        {
            "key": "risk_configured",
            "label": "Limites de risque configurees",
            "done": settings.risk_percent > 0 and settings.max_daily_loss_percent > 0,
            "detail": f"{settings.risk_percent}% par trade, {settings.max_daily_loss_percent}% par jour",
        },
        {
            "key": "emergency_tested",
            "label": "Arret d'urgence teste",
            "done": bool(
                await journal_repo.list_entries(session, limit=1, category="emergency")
            ),
        },
    ]
    completed = sum(1 for item in items if item["done"])
    return {
        "items": items,
        "completed": completed,
        "total": len(items),
        "ready": completed == len(items),
        "disclaimer": (
            "Cette liste aide a verifier la configuration. Elle ne rend en aucun cas "
            "le trading sans risque."
        ),
    }
