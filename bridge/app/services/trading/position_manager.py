"""Gestion des positions ouvertes : TP multiples, break even, trailing, suivi.

Cette couche applique les messages de suivi du canal et les regles automatiques
configurees. Elle ne decide jamais d'ouvrir une nouvelle position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import RiskSettings, utcnow
from app.models.enums import (
    BreakEvenTrigger,
    Direction,
    EventLevel,
    FollowUpAction,
    MultiTpStrategy,
    PositionState,
    SignalStatus,
    TrailingMode,
)
from app.models.trading import Signal, TradeRecord
from app.repositories import signal_repo, trade_repo
from app.services import journal
from app.services.events import EventType, event_bus
from app.services.mt5.interface import MetaTraderService, SymbolInfo, Tick
from app.services.risk.calculator import round_to_step
from app.services.signals.models import FollowUp
from app.services.technical_analysis import indicators
from app.services.trading import announcements

logger = get_logger(__name__)

# Part de la distance de suivi qu'il faut parcourir avant de renvoyer une
# modification au courtier. Sans ce pas, le stop serait reecrit a chaque
# tick : le courtier finirait par refuser les requetes.
TRAILING_STEP_RATIO = 0.25


@dataclass(slots=True)
class ManagementAction:
    kind: str
    ticket: int | None = None
    detail: str = ""
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ticket": self.ticket, "detail": self.detail, "ok": self.ok, **self.data}


@dataclass(slots=True)
class ManagementResult:
    actions: list[ManagementAction] = field(default_factory=list)
    detail: str = ""
    # Positions entierement fermees pendant cette operation. L'appelant DOIT
    # les passer au comptage du risque : la reconciliation ne les verra jamais,
    # puisqu'elle ne repasse que sur les positions encore ouvertes.
    closed: list[TradeRecord] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(action.ok for action in self.actions)

    def add(self, action: ManagementAction) -> None:
        self.actions.append(action)

    def add_closed(self, trade: TradeRecord) -> None:
        self.closed.append(trade)

    def to_dict(self) -> dict[str, Any]:
        return {"actions": [action.to_dict() for action in self.actions], "detail": self.detail}


def break_even_price(trade: TradeRecord, symbol: SymbolInfo, offset_points: int) -> float:
    """Prix de mise a break even : entree, decalee d'un petit tampon."""
    offset = offset_points * symbol.point
    if trade.direction is Direction.BUY:
        return round(trade.open_price + offset, symbol.digits)
    return round(trade.open_price - offset, symbol.digits)


def _respects_stop_distance(price: float, stop: float, symbol: SymbolInfo) -> bool:
    if symbol.trade_stops_level <= 0 or symbol.point <= 0:
        return True
    return abs(price - stop) / symbol.point >= symbol.trade_stops_level


def _stop_is_better(trade: TradeRecord, new_stop: float) -> bool:
    """Un stop ne recule jamais : il ne peut que proteger davantage."""
    if trade.stop_loss is None:
        return True
    if trade.direction is Direction.BUY:
        return new_stop > trade.stop_loss
    return new_stop < trade.stop_loss


def _protege_au_moins_l_entree(trade: TradeRecord, new_stop: float) -> bool:
    """Le stop laisse-t-il la position gagnante, ou au pire a l'equilibre ?"""
    if trade.direction is Direction.BUY:
        return new_stop >= trade.open_price
    return new_stop <= trade.open_price


class PositionManager:
    def __init__(self, service: MetaTraderService) -> None:
        self._service = service

    # ------------------------------------------------------------------
    # Messages de suivi du canal
    # ------------------------------------------------------------------
    async def apply_follow_up(
        self,
        session: AsyncSession,
        follow_up_signal: Signal,
        parent: Signal,
        follow_up: FollowUp,
        settings: RiskSettings,
    ) -> ManagementResult:
        trades = [
            trade
            for trade in await trade_repo.trades_for_signal(session, parent.id)
            if trade.state in (PositionState.OPEN, PositionState.PARTIALLY_CLOSED)
        ]
        orders = await trade_repo.pending_orders(session, signal_id=parent.id)
        result = ManagementResult()

        if follow_up.action is FollowUpAction.CANCEL_PENDING:
            for order in orders:
                cancel = await self._service.cancel_order(order.ticket)
                order.state = PositionState.CANCELLED if cancel.ok else order.state
                await trade_repo.save_order(session, order)
                result.add(
                    ManagementAction("cancel_pending", order.ticket, cancel.message, cancel.ok)
                )
                if cancel.ok:
                    event_bus.publish(EventType.ORDER_CANCELLED, {"ticket": order.ticket})
            if not orders:
                result.detail = "Aucun ordre en attente a annuler"
            await self._finalize(session, follow_up_signal, parent, result, trades)
            return result

        if not trades:
            result.detail = "Aucune position ouverte rattachee a ce signal"
            await signal_repo.add_event(
                session,
                follow_up_signal.id,
                stage="follow_up",
                success=False,
                message=result.detail,
            )
            return result

        if follow_up.action is FollowUpAction.CLOSE_ALL:
            for trade in trades:
                await self._close(session, trade, None, "message de fermeture du canal", result)

        elif follow_up.action is FollowUpAction.CLOSE_PARTIAL:
            percentage = follow_up.percentage or 50.0
            for trade in trades:
                await self._close_partial(
                    session, trade, percentage, "fermeture partielle demandee", result
                )

        elif follow_up.action is FollowUpAction.MOVE_SL_BE:
            for trade in trades:
                await self._move_to_break_even(session, trade, settings, result)

        elif follow_up.action is FollowUpAction.MOVE_SL and follow_up.price is not None:
            for trade in trades:
                await self._set_stop_loss(
                    session, trade, follow_up.price, "SL deplace par le canal", result
                )

        elif follow_up.action is FollowUpAction.MOVE_TP and follow_up.price is not None:
            for trade in trades:
                await self._set_take_profit(session, trade, follow_up.price, result)

        elif follow_up.action is FollowUpAction.TP_HIT:
            index = follow_up.tp_index or 1
            for trade in trades:
                await self._handle_tp_hit(session, trade, index, settings, result)
            if follow_up.also_break_even:
                for trade in trades:
                    await self._move_to_break_even(session, trade, settings, result)

        elif follow_up.action is FollowUpAction.SL_HIT:
            result.detail = "Information de stop loss : la position est geree par le broker"

        else:  # INFO
            result.detail = "Message d'information sans action"

        await self._finalize(session, follow_up_signal, parent, result, trades)
        return result

    async def _finalize(
        self,
        session: AsyncSession,
        follow_up_signal: Signal,
        parent: Signal,
        result: ManagementResult,
        trades: list[TradeRecord],
    ) -> None:
        await signal_repo.add_event(
            session,
            follow_up_signal.id,
            stage="follow_up",
            success=result.ok,
            message=result.detail or f"{len(result.actions)} action(s) appliquee(s)",
            data=result.to_dict(),
        )
        await signal_repo.set_status(
            session,
            follow_up_signal,
            SignalStatus.CLOSED if result.ok else SignalStatus.FAILED,
            stage="follow_up",
            message=result.detail,
            success=result.ok,
        )
        still_open = [t for t in trades if t.state in (PositionState.OPEN, PositionState.PARTIALLY_CLOSED)]
        if not still_open and trades:
            await signal_repo.set_status(
                session,
                parent,
                SignalStatus.CLOSED,
                stage="lifecycle",
                message="Toutes les positions fermees",
            )

    # ------------------------------------------------------------------
    # Actions unitaires
    # ------------------------------------------------------------------
    async def _handle_tp_hit(
        self,
        session: AsyncSession,
        trade: TradeRecord,
        tp_index: int,
        settings: RiskSettings,
        result: ManagementResult,
    ) -> None:
        targets = list(trade.take_profit_targets or [])
        trade.tp_index = max(trade.tp_index, tp_index)
        await trade_repo.save_trade(session, trade)
        result.add(
            ManagementAction(
                "tp_hit",
                trade.ticket,
                f"TP{tp_index} signale par le canal",
                data={"tpIndex": tp_index},
            )
        )

        strategy = settings.multi_tp_strategy
        if strategy is MultiTpStrategy.PARTIAL_CLOSE and targets and tp_index < len(targets):
            ratios = list(settings.split_ratios or [40.0, 30.0, 30.0])
            percentage = ratios[tp_index - 1] if tp_index - 1 < len(ratios) else 33.0
            await self._close_partial(
                session, trade, percentage, f"prise partielle sur TP{tp_index}", result
            )

        if (
            settings.break_even_enabled
            and settings.break_even_trigger is BreakEvenTrigger.TP1_HIT
            and tp_index >= 1
            and not trade.break_even_applied
        ):
            await self._move_to_break_even(session, trade, settings, result)

    async def _move_to_break_even(
        self,
        session: AsyncSession,
        trade: TradeRecord,
        settings: RiskSettings,
        result: ManagementResult,
    ) -> None:
        symbol = await self._service.symbol_info(trade.symbol)
        if symbol is None:
            result.add(ManagementAction("break_even", trade.ticket, "Symbole introuvable", ok=False))
            return
        target = break_even_price(trade, symbol, settings.break_even_offset_points)
        tick = await self._service.symbol_tick(trade.symbol)
        if tick is not None:
            reference = tick.bid if trade.direction is Direction.BUY else tick.ask
            if not _respects_stop_distance(reference, target, symbol):
                result.add(
                    ManagementAction(
                        "break_even",
                        trade.ticket,
                        "Prix trop proche de l'entree : break even refuse par le broker",
                        ok=False,
                    )
                )
                return
        if not _stop_is_better(trade, target):
            result.add(
                ManagementAction("break_even", trade.ticket, "Stop deja au moins aussi protecteur")
            )
            return
        await self._set_stop_loss(session, trade, target, "break even", result, mark_break_even=True)

    async def _set_stop_loss(
        self,
        session: AsyncSession,
        trade: TradeRecord,
        price: float,
        reason: str,
        result: ManagementResult,
        mark_break_even: bool = False,
    ) -> None:
        symbol = await self._service.symbol_info(trade.symbol)
        digits = symbol.digits if symbol else 5
        new_stop = round(price, digits)
        response = await self._service.modify_position(trade.ticket, new_stop, trade.take_profit)
        if response.ok:
            trade.stop_loss = new_stop
            trade.break_even_applied = trade.break_even_applied or mark_break_even
            await trade_repo.save_trade(session, trade)
            event_bus.publish(
                EventType.POSITION_UPDATED,
                {"ticket": trade.ticket, "stopLoss": new_stop, "reason": reason},
            )
            await journal.record(
                session,
                event="sl_modified",
                message=f"SL de {trade.symbol} place a {new_stop} ({reason})",
                category="trading",
                signal_id=trade.signal_id,
            )
        result.add(
            ManagementAction(
                "modify_sl", trade.ticket, response.message or reason, response.ok, {"stopLoss": new_stop}
            )
        )

    async def _set_take_profit(
        self, session: AsyncSession, trade: TradeRecord, price: float, result: ManagementResult
    ) -> None:
        symbol = await self._service.symbol_info(trade.symbol)
        digits = symbol.digits if symbol else 5
        new_tp = round(price, digits)
        response = await self._service.modify_position(trade.ticket, trade.stop_loss, new_tp)
        if response.ok:
            trade.take_profit = new_tp
            await trade_repo.save_trade(session, trade)
            event_bus.publish(EventType.POSITION_UPDATED, {"ticket": trade.ticket, "takeProfit": new_tp})
        result.add(
            ManagementAction("modify_tp", trade.ticket, response.message, response.ok, {"takeProfit": new_tp})
        )

    async def _close_partial(
        self,
        session: AsyncSession,
        trade: TradeRecord,
        percentage: float,
        reason: str,
        result: ManagementResult,
    ) -> None:
        symbol = await self._service.symbol_info(trade.symbol)
        if symbol is None:
            result.add(ManagementAction("close_partial", trade.ticket, "Symbole introuvable", ok=False))
            return
        volume = round_to_step(trade.volume * percentage / 100.0, symbol.volume_step)
        if volume < symbol.volume_min - 1e-9:
            result.add(
                ManagementAction(
                    "close_partial",
                    trade.ticket,
                    f"Volume partiel {volume} sous le minimum broker : fermeture totale a la place",
                )
            )
            await self._close(session, trade, None, reason, result)
            return
        if volume >= trade.volume - 1e-9:
            await self._close(session, trade, None, reason, result)
            return
        await self._close(session, trade, volume, reason, result)

    async def _close(
        self,
        session: AsyncSession,
        trade: TradeRecord,
        volume: float | None,
        reason: str,
        result: ManagementResult,
    ) -> None:
        response = await self._service.close_position(trade.ticket, volume)
        if not response.ok:
            result.add(ManagementAction("close", trade.ticket, response.message, ok=False))
            return

        closed_volume = response.volume or volume or trade.volume
        trade.closed_volume = round(trade.closed_volume + closed_volume, 4)
        trade.volume = round(max(0.0, trade.volume - closed_volume), 4)
        trade.close_reason = reason[:64]
        if response.price:
            trade.close_price = response.price
        if trade.volume <= 1e-9:
            trade.state = PositionState.CLOSED
            trade.closed_at = utcnow()
            # Le resultat definitif vient de l'historique des deals du
            # courtier ; le profit flottant au moment de l'ordre n'en est
            # qu'un repli. Sans cette ligne, le trade restait a 0,00 et
            # n'alimentait aucune limite de risque.
            realized = await self._realized_profits()
            trade.realized_pnl = realized.get(trade.ticket, trade.profit)
        else:
            trade.state = PositionState.PARTIALLY_CLOSED
        await trade_repo.save_trade(session, trade)
        if trade.state is PositionState.CLOSED:
            result.add_closed(trade)

        event_bus.publish(
            EventType.POSITION_CLOSED if trade.state is PositionState.CLOSED else EventType.POSITION_UPDATED,
            {"ticket": trade.ticket, "volume": closed_volume, "reason": reason},
        )
        await journal.record(
            session,
            event="position_closed" if trade.state is PositionState.CLOSED else "partial_close",
            message=f"{trade.symbol} : {closed_volume} lot(s) fermes ({reason})",
            category="trading",
            signal_id=trade.signal_id,
        )
        result.add(
            ManagementAction("close", trade.ticket, reason, True, {"volume": closed_volume})
        )

    # ------------------------------------------------------------------
    # Regles automatiques
    # ------------------------------------------------------------------
    async def apply_automatic_rules(
        self, session: AsyncSession, settings: RiskSettings, trades: list[TradeRecord]
    ) -> ManagementResult:
        """Break even et trailing stop, evalues a chaque cycle de suivi."""
        result = ManagementResult()
        for trade in trades:
            if trade.state not in (PositionState.OPEN, PositionState.PARTIALLY_CLOSED):
                continue
            symbol = await self._service.symbol_info(trade.symbol)
            tick = await self._service.symbol_tick(trade.symbol)
            if symbol is None or tick is None:
                continue
            if settings.break_even_enabled and not trade.break_even_applied:
                await self._auto_break_even(session, trade, settings, symbol, tick, result)
            if settings.trailing_mode is not TrailingMode.DISABLED:
                await self._auto_trailing(session, trade, settings, symbol, tick, result)
        return result

    async def _auto_break_even(
        self,
        session: AsyncSession,
        trade: TradeRecord,
        settings: RiskSettings,
        symbol: SymbolInfo,
        tick: Tick,
        result: ManagementResult,
    ) -> None:
        trigger = settings.break_even_trigger
        if trigger is BreakEvenTrigger.SIGNAL_ONLY:
            return  # declenche par le message du canal, pas automatiquement

        price = tick.bid if trade.direction is Direction.BUY else tick.ask
        progress = (
            price - trade.open_price if trade.direction is Direction.BUY else trade.open_price - price
        )
        if progress <= 0:
            return

        reached = False
        if trigger is BreakEvenTrigger.TP1_HIT:
            # ``tp_index`` dit qu'un objectif est franchi, sans dire qui l'a
            # constate. Ne partir que sur le message du canal laissait le stop
            # sous l'entree des que le canal restait muet : les objectifs lus
            # sur le prix par ``_annoncer_objectifs`` etaient annonces mais
            # sans effet. Constate le 14/09/2026 sur XAUUSDm, TP2 sur 6
            # franchi et stop toujours a sa valeur d'origine.
            reached = trade.tp_index >= 1
        elif trigger is BreakEvenTrigger.POINTS and symbol.point > 0:
            reached = progress / symbol.point >= settings.break_even_points
        elif trigger is BreakEvenTrigger.R_MULTIPLE and trade.initial_stop_loss is not None:
            risk = abs(trade.open_price - trade.initial_stop_loss)
            reached = risk > 0 and progress / risk >= settings.break_even_r_multiple
        if reached:
            await self._move_to_break_even(session, trade, settings, result)

    async def _auto_trailing(
        self,
        session: AsyncSession,
        trade: TradeRecord,
        settings: RiskSettings,
        symbol: SymbolInfo,
        tick: Tick,
        result: ManagementResult,
    ) -> None:
        price = tick.bid if trade.direction is Direction.BUY else tick.ask
        mode = settings.trailing_mode

        if mode is TrailingMode.AFTER_TP1 and trade.tp_index < 1:
            return
        if mode is TrailingMode.R_BASED and trade.initial_stop_loss is not None:
            risk = abs(trade.open_price - trade.initial_stop_loss)
            progress = (
                price - trade.open_price if trade.direction is Direction.BUY else trade.open_price - price
            )
            if risk <= 0 or progress / risk < settings.break_even_r_multiple:
                return

        if mode is TrailingMode.ATR_BASED:
            distance = await self._atr_distance(trade, settings, symbol, price)
        else:
            distance = settings.trailing_distance_points * symbol.point
        if distance <= 0:
            return

        candidate = price - distance if trade.direction is Direction.BUY else price + distance
        candidate = round(candidate, symbol.digits)

        if not _stop_is_better(trade, candidate):
            return
        # Un stop pose du mauvais cote de l'entree n'est pas un suivi : il
        # reduit en silence le risque planifie d'une position qui n'a encore
        # rien acquis. Aucun mode n'avait cette garde ; ATR_BASED et
        # FIXED_DISTANCE resserraient donc des le premier tick, meme en perte.
        # Le suiveur ne prend le relais qu'une fois le point mort depasse : ce
        # qui vient avant est l'affaire du break even.
        if not _protege_au_moins_l_entree(trade, candidate):
            return
        if trade.stop_loss is not None:
            step = self._trailing_step(settings, symbol, distance)
            if abs(candidate - trade.stop_loss) < step:
                return
        if not _respects_stop_distance(price, candidate, symbol):
            return
        await self._set_stop_loss(session, trade, candidate, "trailing stop", result)

    @staticmethod
    def _trailing_step(settings: RiskSettings, symbol: SymbolInfo, distance: float) -> float:
        """Mouvement minimal du stop avant d'envoyer une modification.

        Il ne sert qu'a eviter de harceler le courtier d'une modification par
        tick. En mode ATR il suit la distance retenue, sinon un pas fixe en
        points redeviendrait inadapte d'un instrument a l'autre — le defaut
        meme que ce mode corrige.
        """
        if settings.trailing_mode is TrailingMode.ATR_BASED:
            return distance * TRAILING_STEP_RATIO
        return settings.trailing_step_points * symbol.point

    async def _atr_distance(
        self,
        trade: TradeRecord,
        settings: RiskSettings,
        symbol: SymbolInfo,
        price: float,
    ) -> float:
        """Distance de suivi, en unites de prix, adossee a la volatilite reelle.

        Deux regimes, selon le gain deja acquis :

        * tant que le trade n'a pas depasse ``trailing_tighten_after_r``, on
          laisse respirer a ``trailing_atr_multiple`` ATR ;
        * au-dela, on resserre a ``trailing_atr_tight_multiple`` ATR pour
          proteger le gain constate.

        Sans historique exploitable, on retombe sur la distance en points :
        mieux vaut un suivi imparfait que pas de suivi du tout.
        """
        atr = await self._atr(symbol, settings)
        if atr is None or atr <= 0:
            logger.info(
                "ATR indisponible sur %s : trailing en points pour cette position",
                symbol.name,
            )
            return settings.trailing_distance_points * symbol.point

        multiple = settings.trailing_atr_multiple
        if trade.initial_stop_loss is not None:
            risk = abs(trade.open_price - trade.initial_stop_loss)
            gain = (
                price - trade.open_price
                if trade.direction is Direction.BUY
                else trade.open_price - price
            )
            if risk > 0 and gain / risk >= settings.trailing_tighten_after_r:
                multiple = min(multiple, settings.trailing_atr_tight_multiple)
        return atr * max(multiple, 0.0)

    async def _atr(self, symbol: SymbolInfo, settings: RiskSettings) -> float | None:
        """ATR de l'instrument, jamais fatal : ``None`` si le terminal se tait."""
        period = max(2, int(settings.trailing_atr_period))
        try:
            candles = await self._service.recent_candles(
                symbol.name, settings.trailing_atr_timeframe, period * 4
            )
        except Exception as exc:
            logger.info("Bougies %s indisponibles pour le trailing : %s", symbol.name, exc)
            return None
        return indicators.atr(candles, period)

    # ------------------------------------------------------------------
    # Ordres en attente
    # ------------------------------------------------------------------
    async def _reconcile_pending(
        self,
        session: AsyncSession,
        execution_mode: Any,
        live_by_ticket: dict[int, Any],
    ) -> list[TradeRecord]:
        """Convertit les ordres remplis et retire ceux qui ont disparu.

        Trois issues pour un ordre en attente :
          - son ticket porte maintenant une position : il s'est rempli ;
          - il n'est plus chez le courtier et aucune position ne le porte :
            il a ete annule ou a expire ;
          - il est toujours la : on n'y touche pas.

        Si la liste des ordres du courtier est illisible, on ne conclut rien :
        annuler un ordre encore vivant serait pire que d'attendre un tour.
        """
        en_attente = await trade_repo.pending_orders(session, execution_mode)
        if not en_attente:
            return []

        try:
            live_orders = await self._service.orders()
        except Exception as exc:
            logger.warning(
                "Ordres en attente non reconcilies : lecture impossible (%s).", exc
            )
            return []
        tickets_ouverts = {order.ticket for order in live_orders}

        remplis: list[TradeRecord] = []
        for order in en_attente:
            position = live_by_ticket.get(order.ticket)
            if position is not None:
                trade = await self._promote_order(session, order, position, execution_mode)
                if trade is not None:
                    remplis.append(trade)
                    await announcements.ordre_declenche(
                        session,
                        symbol=trade.symbol,
                        direction=trade.direction,
                        price=trade.open_price,
                        volume=trade.volume,
                        trade_id=trade.id,
                    )
                continue
            if order.ticket in tickets_ouverts:
                continue
            order.state = PositionState.CANCELLED
            order.updated_at = utcnow()
            await trade_repo.save_order(session, order)
            await announcements.ordre_non_declenche(
                session,
                symbol=order.symbol,
                direction=order.direction,
                entry=order.price,
                trade_id=order.id,
            )
            await journal.record(
                session,
                event="order_cancelled",
                message=(
                    f"Ordre en attente {order.symbol} #{order.ticket} disparu du "
                    "terminal : annule ou expire"
                ),
                category="trading",
                level=EventLevel.INFO,
                signal_id=order.signal_id,
            )
        return remplis

    async def _promote_order(
        self,
        session: AsyncSession,
        order: Any,
        position: Any,
        execution_mode: Any,
    ) -> TradeRecord | None:
        """Cree la position suivie correspondant a un ordre rempli."""
        existant = await trade_repo.find_by_ticket(session, order.ticket, execution_mode)
        if existant is not None:
            # Deja promu lors d'un tour precedent : on ne duplique pas.
            order.state = PositionState.OPEN
            order.updated_at = utcnow()
            await trade_repo.save_order(session, order)
            return None

        trade = TradeRecord(
            signal_id=order.signal_id,
            channel_id=order.channel_id,
            execution_mode=execution_mode,
            ticket=order.ticket,
            symbol=order.symbol,
            broker_symbol=position.symbol,
            direction=order.direction,
            initial_volume=position.volume,
            volume=position.volume,
            open_price=position.price_open,
            current_price=position.price_current or position.price_open,
            stop_loss=order.stop_loss,
            # Reference de risque de la position, sans laquelle 1 R n'est pas
            # calculable. Elle manquait : une position nee d'un ordre en
            # attente n'etait donc jamais mise a break even en mode R_MULTIPLE,
            # et le trailing ne se resserrait jamais. Constate le 14/09/2026
            # sur XAUUSDm #3223262501, dont le stop ne pouvait pas remonter.
            initial_stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            profit=position.profit,
            state=PositionState.OPEN,
            opened_at=position.opened_at or utcnow(),
        )
        await trade_repo.save_trade(session, trade)

        order.state = PositionState.OPEN
        order.updated_at = utcnow()
        await trade_repo.save_order(session, order)

        event_bus.publish(
            EventType.POSITION_OPENED,
            {"ticket": trade.ticket, "symbol": trade.symbol, "volume": trade.volume},
        )
        await journal.record(
            session,
            event="pending_order_filled",
            message=(
                f"Ordre en attente {trade.symbol} #{trade.ticket} rempli a "
                f"{trade.open_price} : la position est desormais suivie"
            ),
            category="trading",
            level=EventLevel.INFO,
            signal_id=order.signal_id,
        )
        return trade

    # ------------------------------------------------------------------
    # Reconciliation avec le broker
    # ------------------------------------------------------------------
    async def sync_with_broker(
        self, session: AsyncSession, execution_mode: Any
    ) -> list[TradeRecord]:
        """Aligne la base sur l'etat reel du terminal et detecte les fermetures."""
        try:
            live_positions = await self._service.positions()
        except Exception as exc:
            # Renoncer est le bon choix : sans lecture fiable, toute
            # conclusion sur les fermetures serait une invention. Mais cela
            # doit se voir, sinon le suivi s'arrete en silence.
            logger.warning(
                "Reconciliation reportee : positions illisibles (%s). "
                "Aucune position n'est marquee fermee.",
                exc,
            )
            return []
        live_by_ticket = {position.ticket: position for position in live_positions}
        realized = await self._realized_profits()

        # Un ordre en attente qui s'est rempli devient une position a suivre.
        # A faire AVANT la detection des fermetures, sinon la position ainsi
        # creee serait relue au tour suivant comme une inconnue.
        await self._reconcile_pending(session, execution_mode, live_by_ticket)

        closed: list[TradeRecord] = []
        for trade in await trade_repo.open_trades(session, execution_mode):
            position = live_by_ticket.get(trade.ticket)
            if position is None:
                trade.state = PositionState.CLOSED
                trade.closed_at = trade.closed_at or utcnow()
                trade.close_reason = trade.close_reason or "fermee cote broker"
                # Le resultat definitif vient de l'historique des deals ; le
                # profit flottant n'est qu'un repli lorsqu'il est indisponible.
                trade.realized_pnl = realized.get(trade.ticket, trade.profit)
                await trade_repo.save_trade(session, trade)
                closed.append(trade)
                event_bus.publish(
                    EventType.POSITION_CLOSED,
                    {"ticket": trade.ticket, "symbol": trade.symbol, "profit": trade.profit},
                )
                await announcements.position_fermee(
                    session,
                    symbol=trade.symbol,
                    direction=trade.direction,
                    atteints=trade.tp_index,
                    total=len(trade.take_profit_targets or []),
                    profit=trade.realized_pnl,
                    reason=trade.close_reason,
                    trade_id=trade.id,
                )
                await journal.record(
                    session,
                    event="position_closed",
                    message=(
                        f"Position {trade.symbol} #{trade.ticket} fermee "
                        f"(resultat {trade.realized_pnl:.2f})"
                    ),
                    category="trading",
                    level=EventLevel.INFO,
                    signal_id=trade.signal_id,
                )
                continue

            trade.volume = position.volume
            trade.profit = position.profit
            trade.swap = position.swap
            trade.commission = position.commission
            trade.stop_loss = position.stop_loss
            trade.take_profit = position.take_profit
            await trade_repo.save_trade(session, trade)
            await self._annoncer_objectifs(session, trade, position)
        return closed

    async def _annoncer_objectifs(
        self, session: AsyncSession, trade: TradeRecord, position: Any
    ) -> None:
        """Annonce chaque objectif franchi, un par un, jusqu'au dernier.

        Le courtier ferme la position lui-meme sur son take profit : sans cette
        lecture du prix courant, les objectifs intermediaires d'une strategie
        multi-TP n'etaient jamais annonces. On avance palier par palier plutot
        que de sauter au plus haut atteint, pour que le compte « TP2 sur 3 »
        reste juste meme si deux objectifs tombent dans le meme tour.
        """
        cibles = list(trade.take_profit_targets or [])
        prix = float(getattr(position, "price_current", 0.0) or 0.0)
        if not cibles or not prix:
            return

        for niveau, cible in enumerate(cibles, start=1):
            if niveau <= trade.tp_index or cible is None:
                continue
            franchi = (
                prix >= float(cible)
                if trade.direction is Direction.BUY
                else prix <= float(cible)
            )
            if not franchi:
                break
            trade.tp_index = niveau
            await trade_repo.save_trade(session, trade)
            await announcements.objectif_atteint(
                session,
                symbol=trade.symbol,
                direction=trade.direction,
                level=niveau,
                total=len(cibles),
                price=prix,
                profit=trade.profit,
                remaining_volume=trade.volume,
                trade_id=trade.id,
            )

    async def _realized_profits(self, hours: int = 48) -> dict[int, float]:
        """Resultat net par position, lu dans l'historique des deals du broker."""
        try:
            deals = await self._service.history_deals(utcnow() - timedelta(hours=hours))
        except Exception as exc:
            logger.debug("Historique des deals indisponible : %s", exc)
            return {}
        totals: dict[int, float] = {}
        for deal in deals:
            if not deal.position_id:
                continue
            totals[deal.position_id] = round(
                totals.get(deal.position_id, 0.0) + deal.profit + deal.swap + deal.commission, 2
            )
        return totals
