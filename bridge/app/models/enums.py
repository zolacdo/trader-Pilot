"""Enumerations partagees du domaine TradePilot."""

from __future__ import annotations

from enum import StrEnum


class Direction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"
    BUY_STOP_LIMIT = "BUY_STOP_LIMIT"
    SELL_STOP_LIMIT = "SELL_STOP_LIMIT"


class SignalStatus(StrEnum):
    """Machine d'etat d'un signal (CDC section 64)."""

    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    ORDER_CHECKED = "ORDER_CHECKED"
    SENT = "SENT"
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    MODIFIED = "MODIFIED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    NO_ACTION = "NO_ACTION"
    OBSERVED = "OBSERVED"
    CANCELLED = "CANCELLED"


TERMINAL_SIGNAL_STATUSES = {
    SignalStatus.REJECTED,
    SignalStatus.CLOSED,
    SignalStatus.FAILED,
    SignalStatus.EXPIRED,
    SignalStatus.NO_ACTION,
    SignalStatus.CANCELLED,
}


class ParserSource(StrEnum):
    DETERMINISTIC = "deterministic"
    TEMPLATE = "template"
    AI = "ai"
    MANUAL = "manual"


class ChannelMode(StrEnum):
    OBSERVE = "OBSERVE"
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class ExecutionMode(StrEnum):
    """Destination des ordres. PAPER par defaut (CDC section 71)."""

    PAPER = "PAPER"
    MT5_DEMO = "MT5_DEMO"
    MT5_LIVE = "MT5_LIVE"


class AccountKind(StrEnum):
    DEMO = "DEMO"
    REAL = "REAL"
    UNKNOWN = "UNKNOWN"


class FollowUpAction(StrEnum):
    """Messages de suivi rattaches a un signal existant (CDC section 18)."""

    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    CLOSE_ALL = "CLOSE_ALL"
    CLOSE_PARTIAL = "CLOSE_PARTIAL"
    MOVE_SL_BE = "MOVE_SL_BE"
    MOVE_SL = "MOVE_SL"
    MOVE_TP = "MOVE_TP"
    CANCEL_PENDING = "CANCEL_PENDING"
    INFO = "INFO"


class RejectionReason(StrEnum):
    """Motifs de refus. Toujours journalises pour l'audit (CDC section 25)."""

    BRIDGE_OFFLINE = "BRIDGE_OFFLINE"
    MT5_DISCONNECTED = "MT5_DISCONNECTED"
    AUTO_TRADING_OFF = "AUTO_TRADING_OFF"
    TRADING_PAUSED = "TRADING_PAUSED"
    CHANNEL_DISABLED = "CHANNEL_DISABLED"
    CHANNEL_OBSERVE_MODE = "CHANNEL_OBSERVE_MODE"
    CHANNEL_NOT_ALLOWED = "CHANNEL_NOT_ALLOWED"
    SYMBOL_NOT_ALLOWED = "SYMBOL_NOT_ALLOWED"
    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    DIRECTION_NOT_ALLOWED = "DIRECTION_NOT_ALLOWED"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MISSING_STOP_LOSS = "MISSING_STOP_LOSS"
    MISSING_TAKE_PROFIT = "MISSING_TAKE_PROFIT"
    INVALID_ENTRY = "INVALID_ENTRY"
    INVALID_STOP_LOSS = "INVALID_STOP_LOSS"
    INVALID_TAKE_PROFIT = "INVALID_TAKE_PROFIT"
    RR_TOO_LOW = "RR_TOO_LOW"
    SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"
    MARKET_CLOSED = "MARKET_CLOSED"
    INVALID_VOLUME = "INVALID_VOLUME"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    RISK_TOO_HIGH = "RISK_TOO_HIGH"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    DAILY_RISK_LIMIT = "DAILY_RISK_LIMIT"
    DAILY_PROFIT_TARGET = "DAILY_PROFIT_TARGET"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    MAX_POSITIONS = "MAX_POSITIONS"
    MAX_POSITIONS_SYMBOL = "MAX_POSITIONS_SYMBOL"
    MAX_EXPOSURE = "MAX_EXPOSURE"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    OUTSIDE_TRADING_HOURS = "OUTSIDE_TRADING_HOURS"
    OUTSIDE_TRADING_DAYS = "OUTSIDE_TRADING_DAYS"
    ORDER_CHECK_FAILED = "ORDER_CHECK_FAILED"
    ORDER_SEND_FAILED = "ORDER_SEND_FAILED"
    LOT_LIMIT = "LOT_LIMIT"
    NO_ACTION = "NO_ACTION"
    MANUAL_REJECTION = "MANUAL_REJECTION"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    LIVE_NOT_UNLOCKED = "LIVE_NOT_UNLOCKED"


class MultiTpStrategy(StrEnum):
    """Strategies de gestion des TP multiples (CDC section 28)."""

    FIRST_TP_ONLY = "FIRST_TP_ONLY"
    SPLIT_POSITIONS = "SPLIT_POSITIONS"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    LAST_TP_ONLY = "LAST_TP_ONLY"


class BreakEvenTrigger(StrEnum):
    TP1_HIT = "TP1_HIT"
    R_MULTIPLE = "R_MULTIPLE"
    POINTS = "POINTS"
    SIGNAL_ONLY = "SIGNAL_ONLY"


class TrailingMode(StrEnum):
    DISABLED = "DISABLED"
    FIXED_DISTANCE = "FIXED_DISTANCE"
    AFTER_TP1 = "AFTER_TP1"
    R_BASED = "R_BASED"
    # Distance exprimee en multiples de l'ATR de l'instrument, et non en
    # points. Un « point » ne vaut pas la meme chose d'un actif a l'autre :
    # mesure le 14/09/2026, 200 points valent 4 fois l'ATR M15 d'EURUSD et un
    # centieme de celui de BTCUSD. Aucun nombre de points ne peut convenir aux
    # deux, l'ATR si.
    ATR_BASED = "ATR_BASED"


class PositionState(StrEnum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"


class EventLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ConnectionState(StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    ERROR = "ERROR"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class BacktestOutcome(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    AMBIGUOUS = "AMBIGUOUS"
    UNDETERMINED = "UNDETERMINED"
    OPEN = "OPEN"
