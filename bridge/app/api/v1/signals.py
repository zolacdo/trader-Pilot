"""Routes des signaux : liste, detail complet, validation manuelle, test du parser."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.core import Device, as_utc, utcnow
from app.models.enums import Direction, ExecutionMode, SignalStatus
from app.models.trading import Signal
from app.repositories import channel_repo, journal_repo, settings_repo, signal_repo, trade_repo
from app.schemas.requests import ManualSignalRequest, SignalDecisionRequest
from app.services.security.auth import require_device
from app.services.signals import pipeline
from app.services.trading.engine import trading_engine

router = APIRouter(prefix="/signals", tags=["signaux"])

# Identifiant interne du canal utilise par la route de simulation. Negatif et
# hors de la plage Telegram : il ne peut entrer en conflit avec un vrai canal.
SIMULATION_CHANNEL_TELEGRAM_ID = -1

# Regroupements proposes par les filtres de l'application (CDC section 33).
STATUS_GROUPS: dict[str, list[SignalStatus]] = {
    "accepted": [SignalStatus.APPROVED, SignalStatus.ORDER_CHECKED, SignalStatus.SENT],
    "executed": [
        SignalStatus.SENT,
        SignalStatus.OPEN,
        SignalStatus.PARTIALLY_CLOSED,
        SignalStatus.MODIFIED,
        SignalStatus.CLOSED,
    ],
    "rejected": [SignalStatus.REJECTED, SignalStatus.EXPIRED],
    "error": [SignalStatus.FAILED],
    "review": [SignalStatus.NEEDS_REVIEW],
    "observed": [SignalStatus.OBSERVED],
}

# NO_ACTION ne designe pas un signal refuse mais un message qui n'a jamais
# porte d'ordre : publicite, bilan de journee, cours, vantardise. L'afficher
# produisait des cartes vides -- ni symbole, ni entree, ni stop, 0 % de
# confiance -- qui noyaient les vrais signaux. La ligne reste en base pour la
# trace ; elle ne remonte plus a l'ecran.
HIDDEN_STATUSES: list[SignalStatus] = [SignalStatus.NO_ACTION]

VISIBLE_STATUSES: list[SignalStatus] = [
    status for status in SignalStatus if status not in HIDDEN_STATUSES
]


def _signal_payload(signal: Signal) -> dict[str, Any]:
    return {
        "id": signal.id,
        "channelId": signal.channel_id,
        "telegramMessageId": signal.telegram_message_id,
        "replyToMessageId": signal.reply_to_message_id,
        "receivedAt": signal.received_at.isoformat(),
        "messageDate": signal.message_date.isoformat() if signal.message_date else None,
        "rawText": signal.raw_text,
        "symbol": signal.symbol,
        "normalizedSymbol": signal.normalized_symbol,
        "brokerSymbol": signal.broker_symbol,
        "direction": signal.direction.value if signal.direction else None,
        "orderType": signal.order_type.value if signal.order_type else None,
        "entryMin": signal.entry_min,
        "entryMax": signal.entry_max,
        "entryPrice": signal.entry_price,
        "stopLoss": signal.stop_loss,
        "takeProfits": list(signal.take_profits or []),
        "confidence": signal.confidence,
        "parserSource": signal.parser_source.value,
        "aiModel": signal.ai_model,
        "status": signal.status.value,
        "rejectionReason": signal.rejection_reason.value if signal.rejection_reason else None,
        "rejectionDetail": signal.rejection_detail,
        "originalSignalId": signal.original_signal_id,
        "followUpAction": signal.follow_up_action.value if signal.follow_up_action else None,
        "followUpPayload": signal.follow_up_payload,
        "executionMode": signal.execution_mode.value if signal.execution_mode else None,
        "computedLot": signal.computed_lot,
        "riskAmount": signal.risk_amount,
        "riskReward": signal.risk_reward,
        "expiresAt": signal.expires_at.isoformat() if signal.expires_at else None,
    }


@router.get("")
async def list_signals(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    channel_id: int | None = Query(default=None, alias="channelId"),
    symbol: str | None = Query(default=None),
    direction: Direction | None = Query(default=None),
    group: str | None = Query(default=None, description="accepted|executed|rejected|error|review|observed"),
    today: bool = Query(default=False),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    statuses = STATUS_GROUPS.get(group) if group else None
    if group and statuses is None:
        raise HTTPException(status_code=400, detail=f"Filtre inconnu : {group}")
    if statuses is None:
        # Sans onglet choisi, on montrait TOUT, y compris ce que le moteur
        # avait ecarte a la lecture. On liste donc explicitement ce qui est
        # visible plutot que de ne rien filtrer.
        statuses = VISIBLE_STATUSES

    since: datetime | None = None
    if today:
        since = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    signals = await signal_repo.list_signals(
        session,
        limit=limit,
        offset=offset,
        channel_id=channel_id,
        symbol=symbol,
        direction=direction,
        statuses=statuses,
        since=since,
    )
    return {
        "count": len(signals),
        "offset": offset,
        "limit": limit,
        "items": [_signal_payload(signal) for signal in signals],
    }


@router.get("/pending")
async def pending_signals(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    """Signaux en attente de validation manuelle, non encore expires."""
    signals = await signal_repo.list_signals(session, limit=50, statuses=[SignalStatus.NEEDS_REVIEW])
    now = utcnow()

    def still_valid(signal: Signal) -> bool:
        """Un signal sans date d'expiration reste proposable indefiniment."""
        expires_at = as_utc(signal.expires_at)
        return expires_at is None or expires_at > now

    return [_signal_payload(signal) for signal in signals if still_valid(signal)]


@router.get("/{signal_id}")
async def signal_detail(
    signal_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Detail complet : message, interpretation, validation, risque, ordre, resultat."""
    signal = await signal_repo.get(session, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal inconnu")

    events = await signal_repo.events_for(session, signal_id)
    trades = await trade_repo.trades_for_signal(session, signal_id)
    orders = await trade_repo.pending_orders(session, signal_id=signal_id)
    audit = await journal_repo.list_audit(session, limit=20, signal_id=signal_id)
    channel = await channel_repo.get(session, signal.channel_id) if signal.channel_id else None
    follow_ups = await signal_repo.follow_ups_for(session, signal_id)

    return {
        **_signal_payload(signal),
        "channel": {"id": channel.id, "title": channel.title} if channel else None,
        "timeline": [
            {
                "createdAt": event.created_at.isoformat(),
                "stage": event.stage,
                "status": event.status.value if event.status else None,
                "success": event.success,
                "message": event.message,
                "data": event.data,
            }
            for event in events
        ],
        "trades": [
            {
                "id": trade.id,
                "ticket": trade.ticket,
                "symbol": trade.symbol,
                "direction": trade.direction.value,
                "state": trade.state.value,
                "volume": trade.volume,
                "initialVolume": trade.initial_volume,
                "openPrice": trade.open_price,
                "closePrice": trade.close_price,
                "stopLoss": trade.stop_loss,
                "takeProfit": trade.take_profit,
                "profit": round(trade.profit, 2),
                "realizedPnl": round(trade.realized_pnl, 2),
                "rMultiple": trade.r_multiple,
                "breakEvenApplied": trade.break_even_applied,
                "tpIndex": trade.tp_index,
                "openedAt": trade.opened_at.isoformat(),
                "closedAt": trade.closed_at.isoformat() if trade.closed_at else None,
                "closeReason": trade.close_reason,
            }
            for trade in trades
        ],
        "pendingOrders": [
            {
                "id": order.id,
                "ticket": order.ticket,
                "orderType": order.order_type.value,
                "price": order.price,
                "volume": order.volume,
                "state": order.state.value,
            }
            for order in orders
        ],
        "followUps": [
            _signal_payload(item) for item in follow_ups
        ],
        "audit": [
            {
                "createdAt": entry.created_at.isoformat(),
                "action": entry.action,
                "actor": entry.actor,
                "details": entry.details,
            }
            for entry in audit
        ],
    }


@router.post("/{signal_id}/approve")
async def approve_signal(
    signal_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Validation manuelle : le RiskManager s'applique quand meme integralement."""
    outcome = await trading_engine.approve_manually(session, signal_id)
    if outcome.stage == "not_found":
        raise HTTPException(status_code=404, detail="Signal inconnu")
    return outcome.to_dict()


@router.post("/{signal_id}/reject")
async def reject_signal(
    signal_id: int,
    payload: SignalDecisionRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    outcome = await trading_engine.reject_manually(session, signal_id, payload.reason)
    if outcome.stage == "not_found":
        raise HTTPException(status_code=404, detail="Signal inconnu")
    return outcome.to_dict()


@router.post("/parse-test")
async def parse_test(
    payload: ManualSignalRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Teste le parser sur un texte libre. N'envoie AUCUN ordre et n'ecrit rien."""
    parsed, validation = await pipeline.analyze_text(
        session, payload.text, payload.channel_id, allow_ai=payload.use_ai
    )
    from app.services.signals.follow_up_parser import parse_follow_up

    follow_up = parse_follow_up(payload.text) if not parsed.is_signal else None
    return {
        "parsed": parsed.to_dict(),
        "validation": validation.to_dict(),
        "followUp": follow_up.to_dict() if follow_up else None,
        "note": "Test d'interpretation uniquement : aucun ordre n'est envoye.",
    }


@router.post("/simulate")
async def simulate_message(
    payload: ManualSignalRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Injecte un message dans le moteur COMPLET, en Paper Trading uniquement.

    Permet de rejouer les scenarios de recette (signal complet, message de
    suivi, doublon, limite de perte) sans attendre un vrai message Telegram.
    La route est refusee des que le mode d'execution n'est pas PAPER : aucun
    ordre ne peut donc atteindre un compte MetaTrader, demo ou reel.
    """
    settings = await settings_repo.get_risk_settings(session)
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise HTTPException(
            status_code=409,
            detail=(
                "La simulation n'est autorisee qu'en mode Paper Trading. "
                f"Mode actuel : {settings.execution_mode.value}."
            ),
        )

    channel = await channel_repo.get(session, payload.channel_id) if payload.channel_id else None
    if channel is None:
        # Canal interne dedie aux essais, cree a la demande. Il suit les memes
        # regles que les autres : il demarre en mode OBSERVE.
        channel = await channel_repo.upsert(
            session,
            telegram_id=SIMULATION_CHANNEL_TELEGRAM_ID,
            title="Canal de test TradePilot",
            username=None,
        )

    # Sans identifiant fourni, chaque appel est un message different et peut
    # donc etre rejoue. Fournir deux fois le meme identifiant declenche la
    # protection anti-doublon.
    message_id = payload.message_id or int(utcnow().timestamp() * 1000) % 2_000_000_000
    outcome = await trading_engine.handle_message(
        session,
        text=payload.text,
        channel=channel,
        message_id=message_id,
        message_date=utcnow(),
    )
    channel_settings = await channel_repo.get_settings(session, channel.id)
    return {
        **outcome.to_dict(),
        "channelId": channel.id,
        "channelMode": channel_settings.mode.value if channel_settings else None,
        "executionMode": settings.execution_mode.value,
        "note": (
            "Message rejoue dans le moteur complet (parser, validation, risque, execution). "
            "Le resultat depend de vos reglages reels : un refus est une information utile."
        ),
    }


@router.get("/stats/summary")
async def signals_summary(
    days: int = Query(default=7, ge=1, le=90),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    signals = await signal_repo.list_signals(session, limit=1000, since=since)
    by_status: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for signal in signals:
        by_status[signal.status.value] = by_status.get(signal.status.value, 0) + 1
        if signal.normalized_symbol:
            by_symbol[signal.normalized_symbol] = by_symbol.get(signal.normalized_symbol, 0) + 1
        by_source[signal.parser_source.value] = by_source.get(signal.parser_source.value, 0) + 1
    return {
        "days": days,
        "total": len(signals),
        "byStatus": by_status,
        "bySymbol": by_symbol,
        "byParserSource": by_source,
    }
