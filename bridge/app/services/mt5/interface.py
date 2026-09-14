"""Contrat commun aux implementations MetaTrader 5.

``RealMetaTraderService`` pilote le terminal Windows, ``FakeMetaTraderService``
sert aux tests et au paper trading. Les deux exposent exactement la meme API
asynchrone (CDC section 81).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.enums import AccountKind, Direction, OrderType

# Codes de retour MT5 les plus frequents, traduits pour l'interface.
RETCODE_DONE = 10009
RETCODE_PLACED = 10008
RETCODE_DONE_PARTIAL = 10010

RETCODE_MESSAGES: dict[int, str] = {
    10004: "Requote : le prix a change avant l'execution",
    10006: "Requete refusee par le broker",
    10007: "Requete annulee par le trader",
    10008: "Ordre place",
    10009: "Requete executee",
    10010: "Requete executee partiellement",
    10011: "Erreur de traitement de la requete",
    10012: "Requete expiree",
    10013: "Requete invalide",
    10014: "Volume invalide",
    10015: "Prix invalide",
    10016: "Stops invalides (SL/TP trop proches ou du mauvais cote)",
    10017: "Trading desactive sur le compte",
    10018: "Marche ferme",
    10019: "Fonds insuffisants",
    10020: "Les prix ont change",
    10021: "Aucune cotation pour traiter la requete",
    10024: "Trop de requetes",
    10025: "Aucun changement dans la requete",
    10026: "Trading automatique desactive par le serveur",
    10027: "Trading automatique desactive dans le terminal",
    10030: "Mode de remplissage non supporte",
    10031: "Pas de connexion au serveur de trading",
    10034: "Volume total maximal atteint",
}


def describe_retcode(retcode: int | None) -> str:
    if retcode is None:
        return "Aucun code de retour"
    return RETCODE_MESSAGES.get(retcode, f"Code de retour MT5 {retcode}")


class MetaTraderError(RuntimeError):
    """Erreur remontee par la couche MT5."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class MetaTraderNotAvailable(MetaTraderError):
    """Le paquet MetaTrader5 ou le terminal est absent de cette machine."""


@dataclass(slots=True)
class TerminalInfo:
    connected: bool = False
    trade_allowed: bool = False
    community_account: bool = False
    path: str | None = None
    data_path: str | None = None
    build: int | None = None
    name: str | None = None
    company: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "tradeAllowed": self.trade_allowed,
            "path": self.path,
            "build": self.build,
            "name": self.name,
            "company": self.company,
        }


@dataclass(slots=True)
class AccountInfo:
    login: int
    server: str
    name: str = ""
    company: str = ""
    currency: str = "USD"
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    margin_free: float = 0.0
    margin_level: float = 0.0
    profit: float = 0.0
    leverage: int = 0
    trade_mode: int | None = None
    trade_allowed: bool = False
    limit_orders: int = 0

    @property
    def kind(self) -> AccountKind:
        """0 = demo, 1 = concours, 2 = reel. Sans information : UNKNOWN.

        Aucune supposition n'est faite : un compte indeterminable ne doit
        jamais etre presente comme demo (CDC section 10).
        """
        if self.trade_mode is None:
            return AccountKind.UNKNOWN
        if self.trade_mode in (0, 1):
            return AccountKind.DEMO
        if self.trade_mode == 2:
            return AccountKind.REAL
        return AccountKind.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "login": self.login,
            "server": self.server,
            "name": self.name,
            "company": self.company,
            "currency": self.currency,
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "margin": round(self.margin, 2),
            "marginFree": round(self.margin_free, 2),
            "marginLevel": round(self.margin_level, 2),
            "profit": round(self.profit, 2),
            "leverage": self.leverage,
            "kind": self.kind.value,
            "tradeAllowed": self.trade_allowed,
        }


@dataclass(slots=True)
class SymbolInfo:
    name: str
    digits: int = 5
    point: float = 0.00001
    trade_tick_size: float = 0.00001
    trade_tick_value: float = 1.0
    trade_contract_size: float = 100000.0
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    trade_stops_level: int = 0
    trade_freeze_level: int = 0
    spread: int = 0
    visible: bool = True
    trade_mode: int = 4
    currency_profit: str = "USD"
    currency_margin: str = "USD"
    description: str = ""

    @property
    def tradable(self) -> bool:
        # 0 = desactive, 1 = long only, 2 = short only, 3 = close only, 4 = full
        return self.trade_mode == 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "digits": self.digits,
            "point": self.point,
            "tickSize": self.trade_tick_size,
            "tickValue": self.trade_tick_value,
            "contractSize": self.trade_contract_size,
            "volumeMin": self.volume_min,
            "volumeMax": self.volume_max,
            "volumeStep": self.volume_step,
            "stopsLevel": self.trade_stops_level,
            "freezeLevel": self.trade_freeze_level,
            "spread": self.spread,
            "visible": self.visible,
            "tradable": self.tradable,
            "description": self.description,
        }


@dataclass(slots=True)
class Tick:
    symbol: str
    bid: float
    ask: float
    last: float = 0.0
    time: datetime | None = None

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)

    def spread_points(self, point: float) -> int:
        if point <= 0:
            return 0
        return round(self.spread / point)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "time": self.time.isoformat() if self.time else None,
        }


@dataclass(slots=True)
class PositionInfo:
    ticket: int
    symbol: str
    direction: Direction
    volume: float
    price_open: float
    price_current: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    profit: float = 0.0
    swap: float = 0.0
    commission: float = 0.0
    magic: int = 0
    comment: str = ""
    opened_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "volume": self.volume,
            "openPrice": self.price_open,
            "currentPrice": self.price_current,
            "stopLoss": self.stop_loss,
            "takeProfit": self.take_profit,
            "profit": round(self.profit, 2),
            "swap": round(self.swap, 2),
            "commission": round(self.commission, 2),
            "magic": self.magic,
            "comment": self.comment,
            "openedAt": self.opened_at.isoformat() if self.opened_at else None,
        }


@dataclass(slots=True)
class OrderInfo:
    ticket: int
    symbol: str
    order_type: OrderType
    direction: Direction
    volume: float
    price_open: float
    stop_loss: float | None = None
    take_profit: float | None = None
    magic: int = 0
    comment: str = ""
    created_at: datetime | None = None
    expires_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "orderType": self.order_type.value,
            "direction": self.direction.value,
            "volume": self.volume,
            "price": self.price_open,
            "stopLoss": self.stop_loss,
            "takeProfit": self.take_profit,
            "comment": self.comment,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass(slots=True)
class DealInfo:
    ticket: int
    order: int
    position_id: int
    symbol: str
    volume: float
    price: float
    profit: float
    commission: float
    swap: float
    entry: int
    time: datetime | None
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "order": self.order,
            "positionId": self.position_id,
            "symbol": self.symbol,
            "volume": self.volume,
            "price": self.price,
            "profit": round(self.profit, 2),
            "commission": round(self.commission, 2),
            "swap": round(self.swap, 2),
            "entry": self.entry,
            "time": self.time.isoformat() if self.time else None,
        }


@dataclass(slots=True)
class TradeResult:
    ok: bool
    retcode: int | None = None
    message: str = ""
    order: int | None = None
    deal: int | None = None
    position: int | None = None
    price: float | None = None
    volume: float | None = None
    request: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def failure(cls, message: str, retcode: int | None = None) -> TradeResult:
        return cls(ok=False, retcode=retcode, message=message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "retcode": self.retcode,
            "message": self.message,
            "order": self.order,
            "deal": self.deal,
            "position": self.position,
            "price": self.price,
            "volume": self.volume,
        }


@dataclass(slots=True)
class OrderRequest:
    """Requete normalisee, traduite ensuite dans le dialecte MT5."""

    symbol: str
    direction: Direction
    order_type: OrderType
    volume: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    deviation: int = 20
    magic: int = 0
    comment: str = ""
    expiration: datetime | None = None

    @property
    def is_pending(self) -> bool:
        return self.order_type is not OrderType.MARKET


@dataclass(slots=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.tick_volume,
        }


class MetaTraderService(abc.ABC):
    """API asynchrone commune. Toutes les implementations serialisent leurs appels."""

    name: str = "metatrader"

    @abc.abstractmethod
    async def initialize(self) -> bool: ...

    @abc.abstractmethod
    async def shutdown(self) -> None: ...

    @abc.abstractmethod
    async def is_connected(self) -> bool: ...

    @abc.abstractmethod
    async def terminal_info(self) -> TerminalInfo | None: ...

    @abc.abstractmethod
    async def account_info(self) -> AccountInfo | None: ...

    @abc.abstractmethod
    async def symbols(self) -> list[str]: ...

    @abc.abstractmethod
    async def symbol_info(self, symbol: str) -> SymbolInfo | None: ...

    @abc.abstractmethod
    async def symbol_tick(self, symbol: str) -> Tick | None: ...

    @abc.abstractmethod
    async def ensure_symbol(self, symbol: str) -> bool: ...

    @abc.abstractmethod
    async def positions(self, symbol: str | None = None) -> list[PositionInfo]: ...

    @abc.abstractmethod
    async def orders(self, symbol: str | None = None) -> list[OrderInfo]: ...

    @abc.abstractmethod
    async def history_deals(self, since: datetime, until: datetime | None = None) -> list[DealInfo]: ...

    @abc.abstractmethod
    async def candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]: ...

    @abc.abstractmethod
    async def recent_candles(self, symbol: str, timeframe: str, bars: int) -> list[Candle]:
        """Les ``bars`` dernieres bougies, sans plage de dates.

        A preferer systematiquement a ``candles`` quand on veut simplement
        l'historique recent : une plage de dates oblige le terminal a
        rapatrier ce qui lui manque depuis le serveur du broker, ce qui peut
        bloquer plusieurs minutes.
        """

    @abc.abstractmethod
    async def order_check(self, request: OrderRequest) -> TradeResult: ...

    @abc.abstractmethod
    async def order_send(self, request: OrderRequest) -> TradeResult: ...

    @abc.abstractmethod
    async def modify_position(
        self, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult: ...

    @abc.abstractmethod
    async def close_position(
        self, ticket: int, volume: float | None = None, deviation: int = 20
    ) -> TradeResult: ...

    @abc.abstractmethod
    async def cancel_order(self, ticket: int) -> TradeResult: ...

    @abc.abstractmethod
    async def modify_order(
        self, ticket: int, price: float | None, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult: ...

    @abc.abstractmethod
    async def calculate_margin(
        self, symbol: str, direction: Direction, volume: float, price: float
    ) -> float | None: ...

    @abc.abstractmethod
    async def calculate_profit(
        self, symbol: str, direction: Direction, volume: float, price_open: float, price_close: float
    ) -> float | None: ...
