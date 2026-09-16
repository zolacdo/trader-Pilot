"""Tables de trading : signaux, evenements, ordres, trades, statistiques."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Column, Text
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.core import utcnow
from app.models.enums import (
    AccountKind,
    BacktestOutcome,
    Direction,
    ExecutionMode,
    FollowUpAction,
    OrderType,
    ParserSource,
    PositionState,
    RejectionReason,
    SignalStatus,
)


class Signal(SQLModel, table=True):
    """Signal interprete a partir d'un message Telegram (CDC section 17).

    Toute information absente du message reste NULL : aucune valeur inventee.
    """

    __tablename__ = "signals"

    id: int | None = Field(default=None, primary_key=True)
    channel_id: int | None = Field(default=None, index=True, foreign_key="channels.id")
    # Identifiant du message d'origine : peut depasser l'entier 32 bits.
    telegram_message_id: int | None = Field(default=None, sa_type=BigInteger, index=True)
    reply_to_message_id: int | None = Field(default=None, sa_type=BigInteger)
    idempotency_key: str = Field(index=True, unique=True, max_length=128)

    received_at: datetime = Field(default_factory=utcnow, index=True)
    message_date: datetime | None = Field(default=None, index=True)
    raw_text: str = Field(sa_column=Column(Text))

    # Strategie qui a produit ce signal, quand elle est connue. Le cycle
    # autonome la nomme ; un message Telegram n'en a pas, et rien n'en invente.
    #
    # Elle vit ici plutot que sur la position : tout ce qui decoule d'une
    # execution -- position, ordre en attente, position nee de cet ordre --
    # porte deja ``signal_id``, donc une seule colonne suffit la ou deux et une
    # logique de report auraient ete necessaires.
    strategy: str | None = Field(default=None, max_length=64, index=True)

    symbol: str | None = Field(default=None, max_length=32, index=True)
    normalized_symbol: str | None = Field(default=None, max_length=32, index=True)
    broker_symbol: str | None = Field(default=None, max_length=32)
    direction: Direction | None = Field(default=None, index=True)
    order_type: OrderType | None = Field(default=None)

    entry_min: float | None = Field(default=None)
    entry_max: float | None = Field(default=None)
    entry_price: float | None = Field(default=None)
    stop_loss: float | None = Field(default=None)
    take_profits: list[float] = Field(default_factory=list, sa_column=Column(JSON))

    confidence: float = Field(default=0.0)
    parser_source: ParserSource = Field(default=ParserSource.DETERMINISTIC)
    ai_model: str | None = Field(default=None, max_length=128)

    status: SignalStatus = Field(default=SignalStatus.RECEIVED, index=True)
    rejection_reason: RejectionReason | None = Field(default=None)
    rejection_detail: str | None = Field(default=None, max_length=500)

    original_signal_id: int | None = Field(default=None, index=True)
    follow_up_action: FollowUpAction | None = Field(default=None)
    follow_up_payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    execution_mode: ExecutionMode | None = Field(default=None)
    computed_lot: float | None = Field(default=None)
    risk_amount: float | None = Field(default=None)
    risk_reward: float | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow)


class SignalEvent(SQLModel, table=True):
    """Transition d'etat / etape de pipeline conservee pour l'audit."""

    __tablename__ = "signal_events"

    id: int | None = Field(default=None, primary_key=True)
    signal_id: int = Field(index=True, foreign_key="signals.id")
    created_at: datetime = Field(default_factory=utcnow, index=True)
    stage: str = Field(max_length=48, description="parser, validation, risk, order_check, ...")
    status: SignalStatus | None = Field(default=None)
    success: bool = Field(default=True)
    message: str = Field(default="", sa_column=Column(Text))
    data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class TradeRecord(SQLModel, table=True):
    """Position ouverte puis fermee (MT5 reel/demo ou paper trading)."""

    __tablename__ = "trades"

    id: int | None = Field(default=None, primary_key=True)
    signal_id: int | None = Field(default=None, index=True, foreign_key="signals.id")
    channel_id: int | None = Field(default=None, index=True)
    execution_mode: ExecutionMode = Field(default=ExecutionMode.PAPER, index=True)
    account_kind: AccountKind = Field(default=AccountKind.UNKNOWN)
    account_login: int | None = Field(default=None, sa_type=BigInteger)

    # Les tickets MetaTrader depassent regulierement l'entier 32 bits.
    ticket: int = Field(sa_type=BigInteger, index=True)
    symbol: str = Field(max_length=32, index=True)
    direction: Direction
    state: PositionState = Field(default=PositionState.OPEN, index=True)

    requested_price: float | None = Field(default=None)
    open_price: float = Field(default=0.0)
    close_price: float | None = Field(default=None)
    initial_volume: float = Field(default=0.0)
    volume: float = Field(default=0.0)
    closed_volume: float = Field(default=0.0)

    stop_loss: float | None = Field(default=None)
    take_profit: float | None = Field(default=None)
    initial_stop_loss: float | None = Field(default=None)
    take_profit_targets: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    tp_index: int = Field(default=0, description="Nombre de TP deja atteints")
    break_even_applied: bool = Field(default=False)

    profit: float = Field(default=0.0)
    swap: float = Field(default=0.0)
    commission: float = Field(default=0.0)
    realized_pnl: float = Field(default=0.0)
    r_multiple: float | None = Field(default=None)

    opened_at: datetime = Field(default_factory=utcnow, index=True)
    closed_at: datetime | None = Field(default=None, index=True)
    close_reason: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=64)
    magic: int = Field(default=0)
    updated_at: datetime = Field(default_factory=utcnow)


class PendingOrderRecord(SQLModel, table=True):
    """Ordre en attente (limit/stop) place a partir d'un signal."""

    __tablename__ = "orders"

    id: int | None = Field(default=None, primary_key=True)
    signal_id: int | None = Field(default=None, index=True, foreign_key="signals.id")
    channel_id: int | None = Field(default=None, index=True)
    execution_mode: ExecutionMode = Field(default=ExecutionMode.PAPER)
    # Les tickets MetaTrader depassent regulierement l'entier 32 bits.
    ticket: int = Field(sa_type=BigInteger, index=True)
    symbol: str = Field(max_length=32, index=True)
    direction: Direction
    order_type: OrderType
    volume: float = Field(default=0.0)
    price: float = Field(default=0.0)
    stop_loss: float | None = Field(default=None)
    take_profit: float | None = Field(default=None)
    # Echelle complete des objectifs du signal. Le courtier n'accepte qu'un
    # take profit par ordre, mais la position nee de cet ordre a besoin de
    # toute l'echelle : sans elle, aucune fermeture partielle, ``tp_index``
    # reste a zero et le break even declenche sur TP1 ne peut jamais partir.
    take_profit_targets: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    state: PositionState = Field(default=PositionState.PENDING, index=True)
    expires_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
    comment: str | None = Field(default=None, max_length=64)


class RiskEvent(SQLModel, table=True):
    """Chaque decision du RiskManager, acceptee ou refusee."""

    __tablename__ = "risk_events"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    signal_id: int | None = Field(default=None, index=True)
    approved: bool = Field(default=False, index=True)
    reason: RejectionReason | None = Field(default=None, index=True)
    detail: str | None = Field(default=None, max_length=500)
    checks: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    computed_lot: float | None = Field(default=None)
    risk_amount: float | None = Field(default=None)


class DailyStatistic(SQLModel, table=True):
    """Agregat journalier, global ou par canal (channel_id NULL = global)."""

    __tablename__ = "daily_statistics"

    id: int | None = Field(default=None, primary_key=True)
    day: str = Field(index=True, max_length=10)
    channel_id: int | None = Field(default=None, index=True)
    execution_mode: ExecutionMode = Field(default=ExecutionMode.PAPER)
    trades: int = Field(default=0)
    wins: int = Field(default=0)
    losses: int = Field(default=0)
    break_even: int = Field(default=0)
    gross_profit: float = Field(default=0.0)
    gross_loss: float = Field(default=0.0)
    net_pnl: float = Field(default=0.0)
    max_drawdown: float = Field(default=0.0)
    start_balance: float | None = Field(default=None)
    end_balance: float | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow)


class SymbolMapping(SQLModel, table=True):
    """Correspondance alias Telegram vers symbole canonique puis symbole broker."""

    __tablename__ = "symbol_mappings"

    id: int | None = Field(default=None, primary_key=True)
    alias: str = Field(index=True, unique=True, max_length=32)
    canonical: str = Field(index=True, max_length=32)
    broker_symbol: str | None = Field(default=None, max_length=32)
    auto_detected: bool = Field(default=False)
    enabled: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=utcnow)


class BacktestResult(SQLModel, table=True):
    """Resultat d'un signal historique rejoue sur les cours MT5 (CDC section 14)."""

    __tablename__ = "backtest_results"

    id: int | None = Field(default=None, primary_key=True)
    analysis_id: int = Field(index=True, foreign_key="channel_analysis.id")
    channel_id: int = Field(index=True)
    message_id: int | None = Field(default=None)
    signal_date: datetime | None = Field(default=None)
    symbol: str | None = Field(default=None, max_length=32)
    direction: Direction | None = Field(default=None)
    entry_price: float | None = Field(default=None)
    stop_loss: float | None = Field(default=None)
    take_profit: float | None = Field(default=None)
    outcome: BacktestOutcome = Field(default=BacktestOutcome.UNDETERMINED, index=True)
    r_multiple: float | None = Field(default=None)
    detail: str | None = Field(default=None, max_length=255)


class AiRequest(SQLModel, table=True):
    """Trace des appels OpenRouter (aucun secret, aucune donnee de compte)."""

    __tablename__ = "ai_requests"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    purpose: str = Field(max_length=32, index=True, description="signal_parse | chart_analysis | model_test")
    model: str = Field(max_length=128)
    is_free_model: bool = Field(default=True)
    success: bool = Field(default=False)
    http_status: int | None = Field(default=None)
    latency_ms: int | None = Field(default=None)
    prompt_chars: int = Field(default=0)
    response_chars: int = Field(default=0)
    error: str | None = Field(default=None, max_length=255)
    signal_id: int | None = Field(default=None, index=True)


class AiModelState(SQLModel, table=True):
    """Etat du selecteur de modeles gratuits (CDC section 19)."""

    __tablename__ = "ai_model_state"

    id: int | None = Field(default=1, primary_key=True)
    auto_mode: bool = Field(default=True)
    text_model: str | None = Field(default=None, max_length=128)
    vision_model: str | None = Field(default=None, max_length=128)
    preferred_text_model: str | None = Field(default=None, max_length=128)
    preferred_vision_model: str | None = Field(default=None, max_length=128)
    text_model_ok: bool = Field(default=False)
    vision_model_ok: bool = Field(default=False)
    last_refresh_at: datetime | None = Field(default=None)
    last_test_at: datetime | None = Field(default=None)
    last_latency_ms: int | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=255)
    free_models: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)
