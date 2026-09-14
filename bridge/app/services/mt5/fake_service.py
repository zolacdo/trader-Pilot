"""Simulateur MetaTrader 5 deterministe et purement en memoire.

Utilise par la suite de tests et par le mode PAPER (CDC section 71). Aucune
dependance au paquet MetaTrader5 : le module fonctionne sur toutes les
plateformes. Les cotations et les bougies sont SYNTHETIQUES.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config.logging_config import get_logger
from app.models.enums import AccountKind, Direction
from app.services.mt5._fake_engine import FIRST_TICKET, PaperBook, generate_candles
from app.services.mt5._mapping import TIMEFRAME_MINUTES, round_volume
from app.services.mt5.interface import (
    RETCODE_DONE,
    RETCODE_PLACED,
    AccountInfo,
    Candle,
    DealInfo,
    MetaTraderService,
    OrderInfo,
    OrderRequest,
    PositionInfo,
    SymbolInfo,
    TerminalInfo,
    Tick,
    TradeResult,
)

logger = get_logger(__name__)


class FakeMetaTraderService(MetaTraderService):
    """Terminal MT5 simule : positions, ordres et comptabilite en memoire."""

    name = "paper"

    def __init__(
        self,
        balance: float = 10000.0,
        currency: str = "USD",
        leverage: int = 500,
        account_kind: AccountKind = AccountKind.DEMO,
        login: int = 99000001,
        server: str = "TradePilot-Paper",
    ) -> None:
        self.currency = currency
        self.account_kind = account_kind
        self.login = int(login)
        self.server = server
        self._initial_balance = float(balance)
        self._book = PaperBook(balance=balance, leverage=leverage)
        self._connected = False
        self._lock = asyncio.Lock()

    # --- acces direct au carnet (tests et mode PAPER) --------------------
    @property
    def book(self) -> PaperBook:
        return self._book

    @property
    def balance(self) -> float:
        return self._book.balance

    @balance.setter
    def balance(self, value: float) -> None:
        self._book.balance = float(value)

    @property
    def leverage(self) -> int:
        return self._book.leverage

    def set_price(self, symbol: str, bid: float) -> None:
        """Force le prix bid d'un symbole (pilotage du simulateur)."""
        self._book.set_price(symbol, bid)

    def move_price(self, symbol: str, delta: float) -> None:
        """Deplace le prix bid d'un symbole d'un delta absolu."""
        self._book.set_price(symbol, self._book.bid(symbol) + float(delta))

    def add_symbol(self, info: SymbolInfo, price: float, spread_points: int = 10) -> None:
        """Ajoute un symbole au catalogue simule."""
        self._book.add_symbol(info, price, spread_points)

    def reset(self) -> None:
        """Remet le simulateur dans son etat initial."""
        self._book.reset(self._initial_balance)

    def tick(self) -> list[dict[str, Any]]:
        """Avance la simulation : declenche SL/TP et remplit les ordres en attente.

        Retourne la liste des evenements produits, par exemple
        ``[{"type": "tp_hit", "ticket": 500001, "price": 3355.0}]``.
        """
        events = self._book.run_tick()
        if events:
            logger.debug("Simulateur : %d evenement(s) produit(s)", len(events))
        return events

    # --- cycle de vie ----------------------------------------------------
    async def initialize(self) -> bool:
        self._connected = True
        logger.info("Simulateur MT5 initialise (compte papier %s)", self.server)
        return True

    async def shutdown(self) -> None:
        self._connected = False
        logger.info("Simulateur MT5 arrete")

    async def is_connected(self) -> bool:
        return self._connected

    async def terminal_info(self) -> TerminalInfo | None:
        return TerminalInfo(
            connected=self._connected,
            trade_allowed=True,
            path=None,
            build=0,
            name="TradePilot Paper Terminal",
            company="TradePilot",
        )

    async def account_info(self) -> AccountInfo | None:
        book = self._book
        book.refresh()
        floating = round(sum(p.profit for p in book.positions.values()), 2)
        equity = round(book.balance + floating, 2)
        margin = book.used_margin()
        level = round(equity / margin * 100.0, 2) if margin > 0 else 0.0
        return AccountInfo(
            login=self.login,
            server=self.server,
            name="TradePilot Paper",
            company="TradePilot",
            currency=self.currency,
            balance=round(book.balance, 2),
            equity=equity,
            margin=margin,
            margin_free=round(equity - margin, 2),
            margin_level=level,
            profit=floating,
            leverage=book.leverage,
            trade_mode=0 if self.account_kind is AccountKind.DEMO else 2,
            trade_allowed=True,
            limit_orders=200,
        )

    # --- lecture ---------------------------------------------------------
    async def symbols(self) -> list[str]:
        return sorted(self._book.symbols)

    async def symbol_info(self, symbol: str) -> SymbolInfo | None:
        return self._book.symbols.get(symbol)

    async def symbol_tick(self, symbol: str) -> Tick | None:
        if symbol not in self._book.symbols:
            return None
        return Tick(
            symbol=symbol,
            bid=self._book.bid(symbol),
            ask=self._book.ask(symbol),
            last=self._book.bid(symbol),
            time=datetime.now(tz=UTC),
        )

    async def ensure_symbol(self, symbol: str) -> bool:
        return symbol in self._book.symbols

    async def positions(self, symbol: str | None = None) -> list[PositionInfo]:
        self._book.refresh()
        items = list(self._book.positions.values())
        if symbol:
            items = [p for p in items if p.symbol == symbol]
        return sorted(items, key=lambda p: p.ticket)

    async def orders(self, symbol: str | None = None) -> list[OrderInfo]:
        items = list(self._book.orders.values())
        if symbol:
            items = [o for o in items if o.symbol == symbol]
        return sorted(items, key=lambda o: o.ticket)

    async def history_deals(self, since: datetime, until: datetime | None = None) -> list[DealInfo]:
        end = until or datetime.now(tz=UTC)
        return [d for d in self._book.deals if d.time is not None and since <= d.time <= end]

    async def candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        """Bougies SYNTHETIQUES deterministes (aucune donnee de marche reelle)."""
        info = self._book.symbols.get(symbol)
        if info is None:
            return []
        base = self._book.base_prices.get(symbol, self._book.prices.get(symbol, 100.0))
        return generate_candles(symbol, base, info.digits, timeframe, start, end)

    # --- validation ------------------------------------------------------
    def _check_stops(self, info: SymbolInfo, request: OrderRequest, price: float) -> str:
        """Verifie le cote et la distance minimale du SL et du TP."""
        minimum = info.trade_stops_level * info.point
        buy = request.direction is Direction.BUY
        if request.stop_loss:
            if buy and request.stop_loss >= price:
                return "Stop loss invalide : il doit etre sous le prix d'entree pour un achat"
            if not buy and request.stop_loss <= price:
                return "Stop loss invalide : il doit etre au-dessus du prix d'entree pour une vente"
            if abs(price - request.stop_loss) < minimum:
                return f"Stop loss trop proche : minimum {info.trade_stops_level} points"
        if request.take_profit:
            if buy and request.take_profit <= price:
                return "Take profit invalide : il doit etre au-dessus du prix d'entree pour un achat"
            if not buy and request.take_profit >= price:
                return "Take profit invalide : il doit etre sous le prix d'entree pour une vente"
            if abs(request.take_profit - price) < minimum:
                return f"Take profit trop proche : minimum {info.trade_stops_level} points"
        return ""

    async def recent_candles(self, symbol: str, timeframe: str, bars: int) -> list[Candle]:
        """Meme serie que ``candles``, bornee aux ``bars`` dernieres bougies."""
        minutes = TIMEFRAME_MINUTES.get(timeframe.upper(), 60)
        end = datetime.now(tz=UTC)
        start = end - timedelta(minutes=minutes * max(1, int(bars)))
        series = await self.candles(symbol, timeframe, start, end)
        return series[-max(1, int(bars)):]

    async def order_check(self, request: OrderRequest) -> TradeResult:
        info = self._book.symbols.get(request.symbol)
        if info is None:
            return TradeResult.failure(f"Symbole inconnu du simulateur : {request.symbol}", 10013)

        volume = float(request.volume)
        if volume < info.volume_min or volume > info.volume_max:
            return TradeResult.failure(
                f"Volume {volume} hors bornes [{info.volume_min} ; {info.volume_max}]", 10014
            )
        steps = volume / info.volume_step
        if abs(steps - round(steps)) > 1e-6:
            return TradeResult.failure(f"Volume {volume} non multiple du pas {info.volume_step}", 10014)

        if request.is_pending and not request.price:
            return TradeResult.failure("Un ordre en attente exige un prix d'entree", 10015)
        if request.is_pending and request.price:
            price = float(request.price)
        else:
            price = self._book.entry_price(request.symbol, request.direction)

        stops_error = self._check_stops(info, request, price)
        if stops_error:
            return TradeResult.failure(stops_error, 10016)

        needed = self._book.margin_of(request.symbol, volume, price)
        account = await self.account_info()
        available = account.margin_free if account else 0.0
        if needed > available:
            return TradeResult.failure(
                f"Marge insuffisante : {needed:.2f} {self.currency} requis, {available:.2f} disponibles",
                10019,
            )
        return TradeResult(ok=True, retcode=0, message="Requete valide", price=price, volume=volume)

    # --- ecriture --------------------------------------------------------
    async def order_send(self, request: OrderRequest) -> TradeResult:
        async with self._lock:
            check = await self.order_check(request)
            if not check.ok:
                return check
            book = self._book
            info = book.symbols[request.symbol]
            volume = round_volume(request.volume, info.volume_step, info.volume_min, info.volume_max)
            ticket = book.next_ticket()

            if request.is_pending:
                order = OrderInfo(
                    ticket=ticket,
                    symbol=request.symbol,
                    order_type=request.order_type,
                    direction=request.direction,
                    volume=volume,
                    price_open=round(float(request.price or 0.0), info.digits),
                    stop_loss=request.stop_loss,
                    take_profit=request.take_profit,
                    magic=request.magic,
                    comment=request.comment,
                    created_at=datetime.now(tz=UTC),
                    expires_at=request.expiration,
                )
                book.orders[ticket] = order
                return TradeResult(
                    ok=True,
                    retcode=RETCODE_PLACED,
                    message="Ordre en attente place",
                    order=ticket,
                    price=order.price_open,
                    volume=volume,
                )

            position = book.open_position(
                ticket=ticket,
                symbol=request.symbol,
                direction=request.direction,
                volume=volume,
                price=book.entry_price(request.symbol, request.direction),
                stop_loss=request.stop_loss,
                take_profit=request.take_profit,
                magic=request.magic,
                comment=request.comment,
            )
            return TradeResult(
                ok=True,
                retcode=RETCODE_DONE,
                message="Position ouverte dans le simulateur",
                order=ticket,
                deal=ticket,
                position=ticket,
                price=position.price_open,
                volume=volume,
            )

    async def modify_position(
        self, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult:
        position = self._book.positions.get(ticket)
        if position is None:
            return TradeResult.failure(f"Position {ticket} introuvable", 10013)
        position.stop_loss = stop_loss
        position.take_profit = take_profit
        return TradeResult(
            ok=True,
            retcode=RETCODE_DONE,
            message="Stops mis a jour",
            position=ticket,
            price=position.price_open,
        )

    async def close_position(
        self, ticket: int, volume: float | None = None, deviation: int = 20
    ) -> TradeResult:
        position = self._book.positions.get(ticket)
        if position is None:
            return TradeResult.failure(f"Position {ticket} introuvable", 10013)
        price = self._book.exit_price(position.symbol, position.direction)
        return self._book.close(position, price, volume, reason="manual")

    async def cancel_order(self, ticket: int) -> TradeResult:
        if self._book.orders.pop(ticket, None) is None:
            return TradeResult.failure(f"Ordre en attente {ticket} introuvable", 10013)
        return TradeResult(ok=True, retcode=RETCODE_DONE, message="Ordre en attente annule", order=ticket)

    async def modify_order(
        self, ticket: int, price: float | None, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult:
        order = self._book.orders.get(ticket)
        if order is None:
            return TradeResult.failure(f"Ordre en attente {ticket} introuvable", 10013)
        if price is not None:
            order.price_open = round(float(price), self._book.symbols[order.symbol].digits)
        order.stop_loss = stop_loss
        order.take_profit = take_profit
        return TradeResult(
            ok=True,
            retcode=RETCODE_DONE,
            message="Ordre en attente modifie",
            order=ticket,
            price=order.price_open,
        )

    # --- calculs ----------------------------------------------------------
    async def calculate_margin(
        self, symbol: str, direction: Direction, volume: float, price: float
    ) -> float | None:
        if symbol not in self._book.symbols:
            return None
        return self._book.margin_of(symbol, float(volume), float(price))

    async def calculate_profit(
        self, symbol: str, direction: Direction, volume: float, price_open: float, price_close: float
    ) -> float | None:
        if symbol not in self._book.symbols:
            return None
        return self._book.profit_of(symbol, direction, float(volume), float(price_open), float(price_close))


__all__ = ["FIRST_TICKET", "FakeMetaTraderService"]
