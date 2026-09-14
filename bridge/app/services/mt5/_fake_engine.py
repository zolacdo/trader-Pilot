"""Moteur interne du simulateur MetaTrader 5 (catalogue, prix, carnet, bougies).

ATTENTION : toutes les donnees produites ici sont SYNTHETIQUES. Elles servent
uniquement aux tests automatises et au mode PAPER. Elles ne proviennent d'aucun
broker et ne doivent jamais etre presentees comme des cotations reelles.
"""

from __future__ import annotations

import math
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.enums import Direction, OrderType
from app.services.mt5._mapping import TIMEFRAME_MINUTES, round_volume
from app.services.mt5.interface import (
    RETCODE_DONE,
    Candle,
    DealInfo,
    OrderInfo,
    PositionInfo,
    SymbolInfo,
    TradeResult,
)

FIRST_TICKET = 500001

# Sens d'un ordre en attente cote achat.
_PENDING_BUY = {OrderType.BUY_LIMIT, OrderType.BUY_STOP, OrderType.BUY_STOP_LIMIT}

# name, digits, point, tick_value, contract_size, vol_min, vol_max, vol_step,
# stops_level, spread_points, prix de base (bid), description
_ROWS: tuple[tuple[str, int, float, float, float, float, float, float, int, int, float, str], ...] = (
    ("XAUUSD", 2, 0.01, 1.0, 100.0, 0.01, 50.0, 0.01, 20, 20, 3350.0, "Or contre dollar US"),
    ("XAGUSD", 3, 0.001, 1.0, 5000.0, 0.01, 50.0, 0.01, 30, 30, 31.50, "Argent contre dollar US"),
    ("EURUSD", 5, 0.00001, 1.0, 100000.0, 0.01, 200.0, 0.01, 10, 8, 1.0850, "Euro contre dollar US"),
    ("GBPUSD", 5, 0.00001, 1.0, 100000.0, 0.01, 200.0, 0.01, 10, 10, 1.2650, "Livre contre dollar US"),
    ("AUDUSD", 5, 0.00001, 1.0, 100000.0, 0.01, 200.0, 0.01, 10, 8, 0.6550, "Dollar australien / USD"),
    ("USDJPY", 3, 0.001, 1.0, 100000.0, 0.01, 200.0, 0.01, 10, 10, 155.20, "Dollar US contre yen"),
    ("GBPJPY", 3, 0.001, 1.0, 100000.0, 0.01, 200.0, 0.01, 12, 18, 195.50, "Livre contre yen"),
    ("US30", 1, 0.1, 1.0, 1.0, 0.01, 50.0, 0.01, 20, 20, 44250.0, "Indice Dow Jones 30"),
    ("NAS100", 1, 0.1, 1.0, 1.0, 0.01, 50.0, 0.01, 20, 20, 20150.0, "Indice Nasdaq 100"),
    ("GER40", 1, 0.1, 1.0, 1.0, 0.01, 50.0, 0.01, 20, 15, 18250.0, "Indice DAX 40"),
    ("BTCUSD", 2, 0.01, 1.0, 1.0, 0.01, 10.0, 0.01, 50, 500, 68000.0, "Bitcoin contre dollar US"),
    ("XTIUSD", 2, 0.01, 1.0, 1000.0, 0.01, 50.0, 0.01, 15, 3, 72.50, "Petrole WTI contre dollar US"),
)


def build_catalog() -> dict[str, SymbolInfo]:
    """Catalogue de symboles du simulateur, metadonnees realistes."""
    catalog: dict[str, SymbolInfo] = {}
    for name, digits, point, tick_value, contract, vmin, vmax, vstep, stops, spread, _, desc in _ROWS:
        catalog[name] = SymbolInfo(
            name=name,
            digits=digits,
            point=point,
            trade_tick_size=point,
            trade_tick_value=tick_value,
            trade_contract_size=contract,
            volume_min=vmin,
            volume_max=vmax,
            volume_step=vstep,
            trade_stops_level=stops,
            trade_freeze_level=0,
            spread=spread,
            visible=True,
            trade_mode=4,
            currency_profit="USD",
            currency_margin="USD",
            description=desc,
        )
    return catalog


def build_prices() -> dict[str, float]:
    """Prix bid de depart, plausibles mais totalement synthetiques."""
    return {row[0]: row[10] for row in _ROWS}


def build_spread_points() -> dict[str, int]:
    """Spread fixe exprime en points pour chaque symbole."""
    return {row[0]: row[9] for row in _ROWS}


def _noise(symbol: str, index: int) -> float:
    """Bruit deterministe dans [-1, 1] dependant du symbole et de l'index."""
    seed = zlib.crc32(f"{symbol}|{index}".encode()) & 0xFFFFFFFF
    return (seed % 2001) / 1000.0 - 1.0


def _price_at(symbol: str, base: float, index: int) -> float:
    """Prix synthetique a un index de bougie absolu (fonction pure, reproductible)."""
    wave = 0.010 * math.sin(index / 17.0) + 0.004 * math.sin(index / 5.0)
    return base * (1.0 + wave + 0.0015 * _noise(symbol, index))


def generate_candles(
    symbol: str,
    base_price: float,
    digits: int,
    timeframe: str,
    start: datetime,
    end: datetime,
    limit: int = 5000,
) -> list[Candle]:
    """Genere des bougies SYNTHETIQUES deterministes pour les tests de backtest.

    La serie ne depend que du symbole et de l'horodatage absolu : deux appels
    sur la meme periode renvoient exactement les memes bougies.
    """
    minutes = TIMEFRAME_MINUTES.get(timeframe.upper())
    if minutes is None or end <= start:
        return []
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)

    step_seconds = minutes * 60
    index = int(start.timestamp() // step_seconds)
    current = datetime.fromtimestamp(index * step_seconds, tz=UTC)
    step = timedelta(minutes=minutes)

    candles: list[Candle] = []
    while current <= end and len(candles) < limit:
        open_price = _price_at(symbol, base_price, index)
        close_price = _price_at(symbol, base_price, index + 1)
        amplitude = abs(close_price - open_price) + base_price * 0.0008
        wick = amplitude * (0.4 + 0.3 * abs(_noise(symbol, index + 900000)))
        candles.append(
            Candle(
                time=current,
                open=round(open_price, digits),
                high=round(max(open_price, close_price) + wick, digits),
                low=round(min(open_price, close_price) - wick, digits),
                close=round(close_price, digits),
                tick_volume=200 + int(abs(_noise(symbol, index + 500000)) * 800),
            )
        )
        index += 1
        current += step
    return candles


class PaperBook:
    """Carnet en memoire : prix, positions, ordres en attente et historique."""

    def __init__(self, balance: float, leverage: int) -> None:
        self.balance = float(balance)
        self.leverage = max(1, int(leverage))
        self.symbols: dict[str, SymbolInfo] = build_catalog()
        self.prices: dict[str, float] = build_prices()
        self.base_prices: dict[str, float] = dict(self.prices)
        self.spread_points: dict[str, int] = build_spread_points()
        self.positions: dict[int, PositionInfo] = {}
        self.orders: dict[int, OrderInfo] = {}
        self.deals: list[DealInfo] = []
        self._next_ticket = FIRST_TICKET

    # --- tickets et prix ------------------------------------------------
    def next_ticket(self) -> int:
        ticket = self._next_ticket
        self._next_ticket += 1
        return ticket

    def bid(self, symbol: str) -> float:
        return float(self.prices[symbol])

    def ask(self, symbol: str) -> float:
        info = self.symbols[symbol]
        return round(self.bid(symbol) + self.spread_points.get(symbol, 0) * info.point, info.digits)

    def entry_price(self, symbol: str, direction: Direction) -> float:
        return self.ask(symbol) if direction is Direction.BUY else self.bid(symbol)

    def exit_price(self, symbol: str, direction: Direction) -> float:
        return self.bid(symbol) if direction is Direction.BUY else self.ask(symbol)

    def set_price(self, symbol: str, bid: float) -> None:
        if symbol not in self.symbols:
            raise KeyError(f"Symbole inconnu du simulateur : {symbol}")
        self.prices[symbol] = round(float(bid), self.symbols[symbol].digits)

    def add_symbol(self, info: SymbolInfo, price: float, spread_points: int) -> None:
        self.symbols[info.name] = info
        self.prices[info.name] = float(price)
        self.base_prices[info.name] = float(price)
        self.spread_points[info.name] = int(spread_points)

    def reset(self, balance: float) -> None:
        self.balance = float(balance)
        self.prices = dict(self.base_prices)
        self.positions.clear()
        self.orders.clear()
        self.deals.clear()
        self._next_ticket = FIRST_TICKET

    # --- comptabilite ---------------------------------------------------
    def profit_of(
        self, symbol: str, direction: Direction, volume: float, entry: float, exit_: float
    ) -> float:
        """Profit brut : (sortie - entree) * volume * taille du contrat."""
        sign = 1.0 if direction is Direction.BUY else -1.0
        contract = self.symbols[symbol].trade_contract_size
        return round((exit_ - entry) * sign * float(volume) * contract, 2)

    def margin_of(self, symbol: str, volume: float, price: float) -> float:
        contract = self.symbols[symbol].trade_contract_size
        return round(float(volume) * contract * float(price) / self.leverage, 2)

    def used_margin(self) -> float:
        total = sum(self.margin_of(p.symbol, p.volume, p.price_open) for p in self.positions.values())
        return round(total, 2)

    def refresh(self) -> None:
        """Reevalue prix courant et profit flottant de chaque position."""
        for position in self.positions.values():
            price = self.exit_price(position.symbol, position.direction)
            position.price_current = price
            position.profit = self.profit_of(
                position.symbol, position.direction, position.volume, position.price_open, price
            )

    # --- carnet ----------------------------------------------------------
    def open_position(
        self,
        ticket: int,
        symbol: str,
        direction: Direction,
        volume: float,
        price: float,
        stop_loss: float | None,
        take_profit: float | None,
        magic: int,
        comment: str,
    ) -> PositionInfo:
        now = datetime.now(tz=UTC)
        position = PositionInfo(
            ticket=ticket,
            symbol=symbol,
            direction=direction,
            volume=volume,
            price_open=price,
            price_current=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            magic=magic,
            comment=comment,
            opened_at=now,
        )
        self.positions[ticket] = position
        self.deals.append(
            DealInfo(
                ticket=ticket,
                order=ticket,
                position_id=ticket,
                symbol=symbol,
                volume=volume,
                price=price,
                profit=0.0,
                commission=0.0,
                swap=0.0,
                entry=0,
                time=now,
                comment=comment,
            )
        )
        return position

    def close(
        self, position: PositionInfo, price: float, volume: float | None = None, reason: str = "manual"
    ) -> TradeResult:
        """Fermeture totale ou partielle : credite le profit sur la balance."""
        info = self.symbols[position.symbol]
        target = position.volume if volume is None else min(float(volume), position.volume)
        target = round_volume(target, info.volume_step, info.volume_min, position.volume)
        if target <= 0:
            return TradeResult.failure("Volume de fermeture invalide", 10014)

        profit = self.profit_of(position.symbol, position.direction, target, position.price_open, price)
        self.balance = round(self.balance + profit, 2)
        self.deals.append(
            DealInfo(
                ticket=self.next_ticket(),
                order=position.ticket,
                position_id=position.ticket,
                symbol=position.symbol,
                volume=target,
                price=price,
                profit=profit,
                commission=0.0,
                swap=0.0,
                entry=1,
                time=datetime.now(tz=UTC),
                comment=reason,
            )
        )

        remaining = round(position.volume - target, 8)
        if remaining >= info.volume_min:
            position.volume = remaining
            position.price_current = price
            position.profit = self.profit_of(
                position.symbol, position.direction, remaining, position.price_open, price
            )
        else:
            self.positions.pop(position.ticket, None)
        return TradeResult(
            ok=True,
            retcode=RETCODE_DONE,
            message=f"Position fermee ({reason}), resultat {profit:.2f}",
            position=position.ticket,
            price=price,
            volume=target,
        )

    def is_triggered(self, order: OrderInfo) -> bool:
        """Vrai lorsque le prix courant touche un ordre en attente."""
        entry = order.price_open
        if order.order_type in _PENDING_BUY:
            ask = self.ask(order.symbol)
            return ask <= entry if order.order_type is OrderType.BUY_LIMIT else ask >= entry
        bid = self.bid(order.symbol)
        return bid >= entry if order.order_type is OrderType.SELL_LIMIT else bid <= entry

    def run_tick(self) -> list[dict[str, Any]]:
        """Declenche SL/TP puis remplit les ordres en attente touches."""
        events: list[dict[str, Any]] = []
        for ticket in sorted(self.positions):
            position = self.positions.get(ticket)
            if position is None:
                continue
            price = self.exit_price(position.symbol, position.direction)
            buy = position.direction is Direction.BUY
            stop = position.stop_loss
            take = position.take_profit
            if stop and ((buy and price <= stop) or (not buy and price >= stop)):
                hit, price = "sl_hit", float(stop)
            elif take and ((buy and price >= take) or (not buy and price <= take)):
                hit, price = "tp_hit", float(take)
            else:
                continue
            self.close(position, price, reason=hit)
            events.append({"type": hit, "ticket": ticket, "price": price})

        for ticket in sorted(self.orders):
            order = self.orders.get(ticket)
            if order is None or not self.is_triggered(order):
                continue
            self.orders.pop(ticket, None)
            self.open_position(
                ticket=ticket,
                symbol=order.symbol,
                direction=order.direction,
                volume=order.volume,
                price=order.price_open,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                magic=order.magic,
                comment=order.comment,
            )
            events.append({"type": "pending_filled", "ticket": ticket, "price": order.price_open})

        self.refresh()
        return events


__all__ = ["FIRST_TICKET", "PaperBook", "generate_candles"]
