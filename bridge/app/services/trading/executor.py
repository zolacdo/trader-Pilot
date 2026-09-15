"""Construction et envoi des ordres vers MetaTrader 5 (ou le moteur papier).

Chaque envoi est precede d'un ``order_check`` : un ordre refuse par le broker
ne doit jamais etre envoye en aveugle. Les caracteristiques du symbole sont
relues avant chaque requete (CDC sections 25 et 27).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import utcnow
from app.models.enums import (
    Direction,
    EventLevel,
    ExecutionMode,
    MultiTpStrategy,
    OrderType,
    PositionState,
    RejectionReason,
    SignalStatus,
)
from app.models.trading import PendingOrderRecord, Signal, TradeRecord
from app.repositories import signal_repo
from app.services import journal
from app.services.events import EventType, event_bus
from app.services.mt5.interface import MetaTraderService, OrderRequest, SymbolInfo, Tick
from app.services.risk.calculator import round_to_step, split_volume
from app.services.risk.manager import RiskDecision
from app.services.signals.models import ParsedSignal
from app.services.trading import announcements

logger = get_logger(__name__)

MAGIC_NUMBER = 770425
COMMENT_PREFIX = "TP"

# Tolerance minimale (en points) pour considerer qu'un prix demande equivaut
# au cours actuel et justifie un ordre au marche.
MIN_MARKET_TOLERANCE_POINTS = 10


@dataclass(slots=True)
class PlacedOrder:
    ticket: int
    volume: float
    price: float
    take_profit: float | None
    stop_loss: float | None
    pending: bool
    order_type: OrderType

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "volume": self.volume,
            "price": self.price,
            "takeProfit": self.take_profit,
            "stopLoss": self.stop_loss,
            "pending": self.pending,
            "orderType": self.order_type.value,
        }


@dataclass(slots=True)
class ExecutionOutcome:
    ok: bool
    orders: list[PlacedOrder] = field(default_factory=list)
    reason: RejectionReason | None = None
    detail: str = ""
    requests: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "orders": [order.to_dict() for order in self.orders],
            "reason": self.reason.value if self.reason else None,
            "detail": self.detail,
        }


def resolve_order_type(
    parsed: ParsedSignal, symbol: SymbolInfo, tick: Tick, entry_price: float | None
) -> tuple[OrderType, float | None]:
    """Determine le type d'ordre et le prix a envoyer.

    Lorsque le message ne precise ni LIMIT ni STOP, la decision est prise en
    comparant le prix demande au cours reel : c'est une regle explicite et
    journalisee, pas une invention de donnee.
    """
    if parsed.order_type is not None and parsed.order_type is not OrderType.MARKET:
        return parsed.order_type, entry_price
    if parsed.order_type is OrderType.MARKET or entry_price is None:
        return OrderType.MARKET, None

    market_price = tick.ask if parsed.direction is Direction.BUY else tick.bid
    tolerance_points = max(
        symbol.trade_stops_level,
        tick.spread_points(symbol.point),
        MIN_MARKET_TOLERANCE_POINTS,
    )
    distance_points = abs(entry_price - market_price) / symbol.point if symbol.point else 0
    if distance_points <= tolerance_points:
        return OrderType.MARKET, None

    if parsed.direction is Direction.BUY:
        return (OrderType.BUY_LIMIT if entry_price < market_price else OrderType.BUY_STOP, entry_price)
    return (OrderType.SELL_LIMIT if entry_price > market_price else OrderType.SELL_STOP, entry_price)


def plan_take_profits(
    parsed: ParsedSignal, strategy: MultiTpStrategy, total_volume: float, symbol: SymbolInfo,
    split_ratios: list[float],
) -> list[tuple[float, float | None]]:
    """Retourne la liste (volume, take_profit) des positions a ouvrir."""
    targets = list(parsed.take_profits)
    if not targets:
        return [(total_volume, None)]

    if strategy is MultiTpStrategy.FIRST_TP_ONLY:
        return [(total_volume, targets[0])]
    if strategy is MultiTpStrategy.LAST_TP_ONLY:
        return [(total_volume, targets[-1])]
    if strategy is MultiTpStrategy.PARTIAL_CLOSE:
        # Une seule position portee jusqu'au dernier objectif ; les objectifs
        # intermediaires declenchent des fermetures partielles gerees ensuite.
        return [(total_volume, targets[-1])]

    # SPLIT_POSITIONS : une position par objectif
    ratios = split_ratios[: len(targets)] or [100.0]
    volumes = split_volume(total_volume, ratios, symbol)
    if not volumes:
        logger.info("Fractionnement impossible (volume trop faible) : position unique conservee")
        return [(total_volume, targets[0])]
    return list(zip(volumes, targets[: len(volumes)], strict=False))


class OrderExecutor:
    """Envoie les ordres et enregistre le resultat pour l'audit."""

    def __init__(self, service: MetaTraderService) -> None:
        self._service = service

    async def execute(
        self,
        session: AsyncSession,
        signal: Signal,
        parsed: ParsedSignal,
        decision: RiskDecision,
        execution_mode: ExecutionMode,
        broker_symbol: str,
        symbol: SymbolInfo,
        tick: Tick,
    ) -> ExecutionOutcome:
        if decision.lot is None or decision.lot.volume is None or parsed.direction is None:
            return ExecutionOutcome(
                ok=False, reason=RejectionReason.INVALID_VOLUME, detail="Volume non calcule"
            )

        strategy = (
            decision.effective.multi_tp_strategy
            if decision.effective
            else MultiTpStrategy.PARTIAL_CLOSE
        )
        split_ratios = list(decision.effective.split_ratios) if decision.effective else []
        if not split_ratios:
            split_ratios = [40.0, 30.0, 30.0]
        deviation = decision.effective.max_slippage_points if decision.effective else 20

        order_type, requested_price = resolve_order_type(parsed, symbol, tick, decision.entry_price)
        plan = plan_take_profits(parsed, strategy, decision.lot.volume, symbol, split_ratios)

        stop_loss = round(parsed.stop_loss, symbol.digits) if parsed.stop_loss is not None else None
        placed: list[PlacedOrder] = []
        requests: list[dict[str, Any]] = []

        for index, (volume, take_profit) in enumerate(plan, start=1):
            volume = round_to_step(volume, symbol.volume_step)
            if volume < symbol.volume_min - 1e-9:
                continue

            request = OrderRequest(
                symbol=broker_symbol,
                direction=parsed.direction,
                order_type=order_type,
                volume=volume,
                price=round(requested_price, symbol.digits) if requested_price is not None else None,
                stop_loss=stop_loss,
                take_profit=round(take_profit, symbol.digits) if take_profit is not None else None,
                deviation=deviation,
                magic=MAGIC_NUMBER,
                comment=f"{COMMENT_PREFIX}{signal.id}-{index}"[:31],
            )
            requests.append(
                {
                    "symbol": request.symbol,
                    "direction": request.direction.value,
                    "orderType": request.order_type.value,
                    "volume": request.volume,
                    "price": request.price,
                    "stopLoss": request.stop_loss,
                    "takeProfit": request.take_profit,
                }
            )

            # --- controle prealable obligatoire ---
            check = await self._service.order_check(request)
            await signal_repo.add_event(
                session,
                signal.id,
                stage="order_check",
                success=check.ok,
                message=check.message or "Controle broker effectue",
                data={"request": requests[-1], "result": check.to_dict()},
            )
            if not check.ok:
                await self._fail(session, signal, RejectionReason.ORDER_CHECK_FAILED, check.message)
                return ExecutionOutcome(
                    ok=False,
                    orders=placed,
                    reason=RejectionReason.ORDER_CHECK_FAILED,
                    detail=check.message,
                    requests=requests,
                )

            result = await self._service.order_send(request)
            await signal_repo.add_event(
                session,
                signal.id,
                stage="order_send",
                success=result.ok,
                message=result.message or "Ordre envoye",
                data={"request": requests[-1], "result": result.to_dict()},
            )
            if not result.ok:
                await self._fail(session, signal, RejectionReason.ORDER_SEND_FAILED, result.message)
                return ExecutionOutcome(
                    ok=False,
                    orders=placed,
                    reason=RejectionReason.ORDER_SEND_FAILED,
                    detail=result.message,
                    requests=requests,
                )

            ticket = result.position or result.order or result.deal or 0
            market_price = tick.ask if parsed.direction is Direction.BUY else tick.bid
            fill_price = result.price or request.price or market_price
            placed.append(
                PlacedOrder(
                    ticket=ticket,
                    volume=result.volume or volume,
                    price=fill_price,
                    take_profit=request.take_profit,
                    stop_loss=request.stop_loss,
                    pending=request.is_pending,
                    order_type=order_type,
                )
            )
            await self._persist(
                session,
                signal=signal,
                execution_mode=execution_mode,
                order=placed[-1],
                parsed=parsed,
                symbol_name=broker_symbol,
                targets=list(parsed.take_profits),
                account_login=None,
            )

        if not placed:
            return ExecutionOutcome(
                ok=False,
                reason=RejectionReason.INVALID_VOLUME,
                detail="Aucun ordre n'a pu etre construit avec un volume valide",
                requests=requests,
            )

        return ExecutionOutcome(ok=True, orders=placed, requests=requests)

    async def _fail(
        self, session: AsyncSession, signal: Signal, reason: RejectionReason, detail: str
    ) -> None:
        signal.rejection_reason = reason
        signal.rejection_detail = detail[:500]
        await signal_repo.set_status(
            session, signal, SignalStatus.FAILED, stage="execution", message=detail, success=False
        )
        await journal.record(
            session,
            event="order_failed",
            message=f"Envoi refuse : {detail}",
            level=EventLevel.ERROR,
            category="trading",
            signal_id=signal.id,
        )
        event_bus.publish(
            EventType.ERROR, {"signalId": signal.id, "reason": reason.value, "detail": detail}
        )

    async def _persist(
        self,
        session: AsyncSession,
        signal: Signal,
        execution_mode: ExecutionMode,
        order: PlacedOrder,
        parsed: ParsedSignal,
        symbol_name: str,
        targets: list[float],
        account_login: int | None,
    ) -> None:
        if order.pending:
            record = PendingOrderRecord(
                signal_id=signal.id,
                channel_id=signal.channel_id,
                execution_mode=execution_mode,
                ticket=order.ticket,
                symbol=symbol_name,
                direction=parsed.direction,
                order_type=order.order_type,
                volume=order.volume,
                price=order.price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                # L'ordre emporte son echelle : la position qui en naitra ne
                # peut plus la deviner autrement, et sans elle toute la gestion
                # automatique reste eteinte.
                take_profit_targets=list(targets),
                state=PositionState.PENDING,
                comment=f"{COMMENT_PREFIX}{signal.id}",
            )
            session.add(record)
            event_bus.publish(EventType.ORDER_PLACED, {"signalId": signal.id, **order.to_dict()})
            # Ce cas passait inapercu : l'utilisateur voyait un signal accepte
            # et supposait une position ouverte, alors que l'ordre attendait un
            # prix qui ne reviendrait peut-etre jamais.
            await announcements.ordre_en_attente(
                session,
                symbol=symbol_name,
                direction=parsed.direction,
                order_type=order.order_type,
                entry=order.price,
                stop_loss=order.stop_loss,
                take_profits=list(targets),
            )
        else:
            record = TradeRecord(
                signal_id=signal.id,
                channel_id=signal.channel_id,
                execution_mode=execution_mode,
                account_login=account_login,
                ticket=order.ticket,
                symbol=symbol_name,
                direction=parsed.direction,
                state=PositionState.OPEN,
                requested_price=parsed.entry_price,
                open_price=order.price,
                initial_volume=order.volume,
                volume=order.volume,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                initial_stop_loss=order.stop_loss,
                take_profit_targets=targets,
                magic=MAGIC_NUMBER,
                comment=f"{COMMENT_PREFIX}{signal.id}",
                opened_at=utcnow(),
            )
            session.add(record)
            event_bus.publish(EventType.POSITION_OPENED, {"signalId": signal.id, **order.to_dict()})
        await session.flush()
