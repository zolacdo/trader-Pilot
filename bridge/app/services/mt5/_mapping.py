"""Conversions entre les structures brutes MetaTrader 5 et les dataclasses TradePilot.

Les objets renvoyes par le paquet ``MetaTrader5`` sont des namedtuples C dont
les champs varient legerement selon le build du terminal. Depuis l'isolation de
MetaTrader5 dans un processus dedie, ces namedtuples sont convertis en ``dict``
avant de traverser la frontiere de processus : les fonctions de mapping lisent
donc chaque champ via :func:`read_field`, qui accepte indifferemment un ``dict``
ou un objet. Les horodatages sont normalises en ``datetime`` UTC.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.models.enums import Direction, OrderType
from app.services.mt5.interface import (
    AccountInfo,
    Candle,
    DealInfo,
    OrderInfo,
    PositionInfo,
    SymbolInfo,
    TerminalInfo,
    Tick,
    TradeResult,
    describe_retcode,
)

# Libelles de timeframe acceptes par l'API TradePilot -> nom de la constante MT5.
TIMEFRAME_CONSTANTS: dict[str, str] = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
    "W1": "TIMEFRAME_W1",
}

# Duree d'une bougie en minutes (utilisee aussi par le simulateur).
TIMEFRAME_MINUTES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
    "W1": 10080,
}

# Codes de type d'ordre MT5 -> (type TradePilot, sens).
ORDER_TYPE_FROM_MT5: dict[int, tuple[OrderType, Direction]] = {
    0: (OrderType.MARKET, Direction.BUY),
    1: (OrderType.MARKET, Direction.SELL),
    2: (OrderType.BUY_LIMIT, Direction.BUY),
    3: (OrderType.SELL_LIMIT, Direction.SELL),
    4: (OrderType.BUY_STOP, Direction.BUY),
    5: (OrderType.SELL_STOP, Direction.SELL),
    6: (OrderType.BUY_STOP_LIMIT, Direction.BUY),
    7: (OrderType.SELL_STOP_LIMIT, Direction.SELL),
}

# (type TradePilot, sens) -> nom de la constante MT5 correspondante.
ORDER_TYPE_TO_MT5: dict[tuple[OrderType, Direction], str] = {
    (OrderType.MARKET, Direction.BUY): "ORDER_TYPE_BUY",
    (OrderType.MARKET, Direction.SELL): "ORDER_TYPE_SELL",
    (OrderType.BUY_LIMIT, Direction.BUY): "ORDER_TYPE_BUY_LIMIT",
    (OrderType.BUY_LIMIT, Direction.SELL): "ORDER_TYPE_BUY_LIMIT",
    (OrderType.SELL_LIMIT, Direction.BUY): "ORDER_TYPE_SELL_LIMIT",
    (OrderType.SELL_LIMIT, Direction.SELL): "ORDER_TYPE_SELL_LIMIT",
    (OrderType.BUY_STOP, Direction.BUY): "ORDER_TYPE_BUY_STOP",
    (OrderType.BUY_STOP, Direction.SELL): "ORDER_TYPE_BUY_STOP",
    (OrderType.SELL_STOP, Direction.BUY): "ORDER_TYPE_SELL_STOP",
    (OrderType.SELL_STOP, Direction.SELL): "ORDER_TYPE_SELL_STOP",
    (OrderType.BUY_STOP_LIMIT, Direction.BUY): "ORDER_TYPE_BUY_STOP_LIMIT",
    (OrderType.BUY_STOP_LIMIT, Direction.SELL): "ORDER_TYPE_BUY_STOP_LIMIT",
    (OrderType.SELL_STOP_LIMIT, Direction.BUY): "ORDER_TYPE_SELL_STOP_LIMIT",
    (OrderType.SELL_STOP_LIMIT, Direction.SELL): "ORDER_TYPE_SELL_STOP_LIMIT",
}


def to_utc(raw: Any) -> datetime | None:
    """Convertit un horodatage MT5 (secondes ou millisecondes) en datetime UTC."""
    if raw in (None, 0):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    # MT5 expose parfois des champs en millisecondes (time_msc).
    if value > 1e11:
        value /= 1000.0
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def round_price(value: float | None, digits: int) -> float | None:
    """Arrondit un prix au nombre de decimales du symbole."""
    if value is None:
        return None
    return round(float(value), max(0, int(digits)))


def round_volume(volume: float, step: float, minimum: float = 0.0, maximum: float | None = None) -> float:
    """Arrondit un volume au pas du symbole et le borne si demande."""
    step = float(step) if step and step > 0 else 0.01
    steps = math.floor((float(volume) / step) + 1e-9)
    rounded = round(steps * step, 8)
    if minimum and rounded < minimum:
        rounded = float(minimum)
    if maximum is not None and rounded > maximum:
        rounded = float(maximum)
    # 8 decimales suffisent : les pas de volume MT5 vont rarement sous 0.001.
    return round(rounded, 8)


def read_field(raw: Any, field: str, default: Any = None) -> Any:
    """Lit un champ, que la source soit un ``dict`` ou un objet a attributs.

    Le processus MT5 renvoie des ``dict`` ; les tests et le simulateur peuvent
    fournir des objets. Les deux formes sont acceptees.
    """
    if raw is None:
        return default
    if isinstance(raw, dict):
        value = raw.get(field, default)
    else:
        value = getattr(raw, field, default)
    return default if value is None else value


def _num(raw: Any, field: str, default: float = 0.0) -> float:
    value = read_field(raw, field, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(raw: Any, field: str, default: int = 0) -> int:
    value = read_field(raw, field, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _str(raw: Any, field: str, default: str = "") -> str:
    value = read_field(raw, field, default)
    return str(value) if value is not None else default


def _stamp(raw: Any, *fields: str) -> Any:
    """Premier horodatage non nul parmi ``fields`` (time_msc puis time)."""
    for field in fields:
        value = read_field(raw, field, None)
        if value:
            return value
    return None


def map_terminal_info(raw: Any) -> TerminalInfo:
    return TerminalInfo(
        connected=bool(read_field(raw, "connected", False)),
        trade_allowed=bool(read_field(raw, "trade_allowed", False)),
        community_account=bool(read_field(raw, "community_account", False)),
        path=_str(raw, "path") or None,
        data_path=_str(raw, "data_path") or None,
        build=_int(raw, "build") or None,
        name=_str(raw, "name") or None,
        company=_str(raw, "company") or None,
    )


def map_account_info(raw: Any) -> AccountInfo:
    trade_mode = read_field(raw, "trade_mode", None)
    return AccountInfo(
        login=_int(raw, "login"),
        server=_str(raw, "server"),
        name=_str(raw, "name"),
        company=_str(raw, "company"),
        currency=_str(raw, "currency", "USD") or "USD",
        balance=_num(raw, "balance"),
        equity=_num(raw, "equity"),
        margin=_num(raw, "margin"),
        margin_free=_num(raw, "margin_free"),
        margin_level=_num(raw, "margin_level"),
        profit=_num(raw, "profit"),
        leverage=_int(raw, "leverage"),
        trade_mode=int(trade_mode) if trade_mode is not None else None,
        trade_allowed=bool(read_field(raw, "trade_allowed", False)),
        limit_orders=_int(raw, "limit_orders"),
    )


def map_symbol_info(raw: Any) -> SymbolInfo:
    digits = _int(raw, "digits", 5)
    point = _num(raw, "point", 10**-digits if digits else 0.00001)
    return SymbolInfo(
        name=_str(raw, "name"),
        digits=digits,
        point=point or 0.00001,
        trade_tick_size=_num(raw, "trade_tick_size", point or 0.00001),
        trade_tick_value=_num(raw, "trade_tick_value", 1.0),
        trade_contract_size=_num(raw, "trade_contract_size", 100000.0),
        volume_min=_num(raw, "volume_min", 0.01),
        volume_max=_num(raw, "volume_max", 100.0),
        volume_step=_num(raw, "volume_step", 0.01),
        trade_stops_level=_int(raw, "trade_stops_level"),
        trade_freeze_level=_int(raw, "trade_freeze_level"),
        spread=_int(raw, "spread"),
        visible=bool(read_field(raw, "visible", True)),
        trade_mode=_int(raw, "trade_mode", 4),
        currency_profit=_str(raw, "currency_profit", "USD"),
        currency_margin=_str(raw, "currency_margin", "USD"),
        description=_str(raw, "description"),
    )


def map_tick(symbol: str, raw: Any) -> Tick:
    stamp = _stamp(raw, "time_msc", "time")
    return Tick(
        symbol=symbol,
        bid=_num(raw, "bid"),
        ask=_num(raw, "ask"),
        last=_num(raw, "last"),
        time=to_utc(stamp),
    )


def map_position(raw: Any) -> PositionInfo:
    direction = Direction.SELL if _int(raw, "type") == 1 else Direction.BUY
    stop_loss = _num(raw, "sl")
    take_profit = _num(raw, "tp")
    return PositionInfo(
        ticket=_int(raw, "ticket"),
        symbol=_str(raw, "symbol"),
        direction=direction,
        volume=_num(raw, "volume"),
        price_open=_num(raw, "price_open"),
        price_current=_num(raw, "price_current"),
        stop_loss=stop_loss or None,
        take_profit=take_profit or None,
        profit=_num(raw, "profit"),
        swap=_num(raw, "swap"),
        commission=_num(raw, "commission"),
        magic=_int(raw, "magic"),
        comment=_str(raw, "comment"),
        opened_at=to_utc(_stamp(raw, "time_msc", "time")),
    )


def map_order(raw: Any) -> OrderInfo:
    order_type, direction = ORDER_TYPE_FROM_MT5.get(_int(raw, "type"), (OrderType.MARKET, Direction.BUY))
    stop_loss = _num(raw, "sl")
    take_profit = _num(raw, "tp")
    price = _num(raw, "price_open") or _num(raw, "price_current")
    return OrderInfo(
        ticket=_int(raw, "ticket"),
        symbol=_str(raw, "symbol"),
        order_type=order_type,
        direction=direction,
        volume=_num(raw, "volume_current") or _num(raw, "volume_initial"),
        price_open=price,
        stop_loss=stop_loss or None,
        take_profit=take_profit or None,
        magic=_int(raw, "magic"),
        comment=_str(raw, "comment"),
        created_at=to_utc(_stamp(raw, "time_setup_msc", "time_setup")),
        expires_at=to_utc(_stamp(raw, "time_expiration")),
    )


def map_deal(raw: Any) -> DealInfo:
    return DealInfo(
        ticket=_int(raw, "ticket"),
        order=_int(raw, "order"),
        position_id=_int(raw, "position_id"),
        symbol=_str(raw, "symbol"),
        volume=_num(raw, "volume"),
        price=_num(raw, "price"),
        profit=_num(raw, "profit"),
        commission=_num(raw, "commission"),
        swap=_num(raw, "swap"),
        entry=_int(raw, "entry"),
        time=to_utc(_stamp(raw, "time_msc", "time")),
        comment=_str(raw, "comment"),
    )


def map_candle(row: Any) -> Candle | None:
    """Convertit une ligne de ``copy_rates_range`` (dict ou ligne numpy)."""
    try:
        stamp = to_utc(row["time"])
        if stamp is None:
            return None
        return Candle(
            time=stamp,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_volume=int(row["tick_volume"]),
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def filling_mode(api: Any, raw_info: Any, pending: bool) -> int:
    """Mode de remplissage supporte par le symbole (bitmask 1 = FOK, 2 = IOC).

    Les ordres en attente utilisent toujours ORDER_FILLING_RETURN.
    """
    if pending:
        return int(getattr(api, "ORDER_FILLING_RETURN", 2))
    mask = _int(raw_info, "filling_mode", 0)
    if mask & 1:
        return int(getattr(api, "ORDER_FILLING_FOK", 0))
    if mask & 2:
        return int(getattr(api, "ORDER_FILLING_IOC", 1))
    return int(getattr(api, "ORDER_FILLING_RETURN", 2))


def build_order_payload(
    api: Any, request: Any, raw_info: Any, info: SymbolInfo, price: float
) -> tuple[dict[str, Any] | None, str]:
    """Traduit une OrderRequest dans le dialecte MT5. Retourne (requete, erreur)."""
    volume = round_volume(request.volume, info.volume_step, info.volume_min, info.volume_max)
    if volume <= 0:
        return None, "Volume invalide apres arrondi au pas du symbole"

    type_name = ORDER_TYPE_TO_MT5.get((request.order_type, request.direction))
    if type_name is None:
        return None, f"Type d'ordre non supporte : {request.order_type}"
    order_type = getattr(api, type_name, None)
    if order_type is None:  # pragma: no cover - build MT5 exotique
        return None, f"Constante MT5 absente : {type_name}"

    pending = bool(request.is_pending)
    action = "TRADE_ACTION_PENDING" if pending else "TRADE_ACTION_DEAL"
    payload: dict[str, Any] = {
        "action": int(getattr(api, action)),
        "symbol": request.symbol,
        "volume": volume,
        "type": int(order_type),
        "price": round_price(price, info.digits),
        "deviation": int(request.deviation),
        "magic": int(request.magic),
        "comment": str(request.comment)[:31],
        "type_time": int(getattr(api, "ORDER_TIME_GTC", 0)),
        "type_filling": filling_mode(api, raw_info, pending),
    }
    if request.stop_loss:
        payload["sl"] = round_price(request.stop_loss, info.digits)
    if request.take_profit:
        payload["tp"] = round_price(request.take_profit, info.digits)
    if pending and request.expiration is not None:
        payload["type_time"] = int(getattr(api, "ORDER_TIME_SPECIFIED", 1))
        payload["expiration"] = request.expiration
    if request.order_type in (OrderType.BUY_STOP_LIMIT, OrderType.SELL_STOP_LIMIT):
        payload["stoplimit"] = payload["price"]
    return payload, ""


def result_from_raw(raw: Any, payload: dict[str, Any], ok_retcodes: set[int]) -> TradeResult:
    """Transforme la reponse MT5 en TradeResult avec un message francais lisible."""
    retcode = _int(raw, "retcode", 0)
    comment = _str(raw, "comment")
    message = describe_retcode(retcode)
    if comment and comment.lower() not in {"request executed", "done"}:
        message = f"{message} ({comment})"
    return TradeResult(
        ok=retcode in ok_retcodes,
        retcode=retcode,
        message=message,
        order=_int(raw, "order") or None,
        deal=_int(raw, "deal") or None,
        position=_int(raw, "position") or None,
        price=_num(raw, "price") or None,
        volume=_num(raw, "volume") or None,
        request=payload,
    )


__all__ = [
    "ORDER_TYPE_FROM_MT5",
    "ORDER_TYPE_TO_MT5",
    "TIMEFRAME_CONSTANTS",
    "TIMEFRAME_MINUTES",
    "build_order_payload",
    "filling_mode",
    "map_account_info",
    "map_candle",
    "map_deal",
    "map_order",
    "map_position",
    "map_symbol_info",
    "map_terminal_info",
    "map_tick",
    "read_field",
    "result_from_raw",
    "round_price",
    "round_volume",
    "to_utc",
]
