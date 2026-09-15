"""Tables du Market Watcher (CDC3 sections 31, 38 et 39).

Toutes les tables sont prefixees ``watcher_`` : le sous-systeme est etanche,
il ne touche a aucune table du Bridge existant et ne peut donc rien casser.

Les dates sont stockees en UTC (CDC3 section 67). La normalisation des
colonnes est rappelee en fin de module : elle doit valoir meme si ces modeles
sont importes apres ``app.models``, ce qui est le cas ici.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Column, Text
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.core import normalize_datetime_columns, utcnow
from app.models.enums import Direction

STRATEGY_VERSION = "market_watcher_v1.0"


class WatcherDecision(StrEnum):
    """Les huit decisions possibles du moteur (CDC3 section 23).

    Le systeme n'est jamais oblige de produire un BUY ou un SELL : NO_TRADE
    et WAIT sont des reponses completes, pas des echecs.
    """

    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WATCH_BUY = "WATCH_BUY"
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"
    WATCH_SELL = "WATCH_SELL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"

    @property
    def is_tradable(self) -> bool:
        """Seules ces quatre decisions donnent lieu a un signal publie."""
        return self in (
            WatcherDecision.STRONG_BUY,
            WatcherDecision.BUY,
            WatcherDecision.SELL,
            WatcherDecision.STRONG_SELL,
        )

    @property
    def is_watch(self) -> bool:
        return self in (WatcherDecision.WATCH_BUY, WatcherDecision.WATCH_SELL)

    @property
    def direction(self) -> Direction | None:
        """Sens implique. ``None`` pour WAIT et NO_TRADE."""
        if self in (WatcherDecision.STRONG_BUY, WatcherDecision.BUY, WatcherDecision.WATCH_BUY):
            return Direction.BUY
        if self in (WatcherDecision.STRONG_SELL, WatcherDecision.SELL, WatcherDecision.WATCH_SELL):
            return Direction.SELL
        return None


class WatcherStatus(StrEnum):
    """Cycle de vie d'un signal publie (CDC3 section 31)."""

    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    TP3_HIT = "TP3_HIT"
    SL_HIT = "SL_HIT"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


# Etats apres lesquels plus rien n'est suivi : le signal est clos.
TERMINAL_STATUSES: frozenset[WatcherStatus] = frozenset(
    {
        WatcherStatus.TP3_HIT,
        WatcherStatus.SL_HIT,
        WatcherStatus.INVALIDATED,
        WatcherStatus.EXPIRED,
        WatcherStatus.CANCELLED,
    }
)

# Etats encore suivis par la boucle de cycle de vie.
OPEN_STATUSES: frozenset[WatcherStatus] = frozenset(
    {
        WatcherStatus.CREATED,
        WatcherStatus.CONFIRMED,
        WatcherStatus.ACTIVE,
        WatcherStatus.TP1_HIT,
        WatcherStatus.TP2_HIT,
    }
)


class EntryType(StrEnum):
    """Nature de l'entree proposee (CDC3 section 26)."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    BREAKOUT = "BREAKOUT"
    RETEST = "RETEST"


class VolatilityLevel(StrEnum):
    """Classification de la volatilite courante (CDC3 section 11)."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class RiskVerdict(StrEnum):
    """Verdict du Risk Manager (CDC3 section 30)."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WAIT = "WAIT"


class VolumeKind(StrEnum):
    """Nature du volume reellement disponible (CDC3 section 12).

    Ne jamais presenter un tick volume comme du volume reel : la distinction
    est portee jusque dans la base et jusque dans le message Telegram.
    """

    REAL = "REAL"
    TICK = "TICK"
    UNKNOWN = "UNKNOWN"


class WatcherSignal(SQLModel, table=True):
    """Un signal produit par le Market Watcher (CDC3 section 39).

    Aucun de ces niveaux ne vient d'un modele de langage : Entry, SL et TP
    sont calcules sur les bougies reelles avant tout appel a l'IA
    (CDC3 section 22).
    """

    __tablename__ = "watcher_signals"

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=32)
    broker_symbol: str = Field(max_length=64)
    direction: Direction
    decision: WatcherDecision
    status: WatcherStatus = Field(default=WatcherStatus.CREATED, index=True)

    # Unite de temps de travail retenue pour ce signal : sans elle, les
    # statistiques par timeframe (CDC3 section 40) seraient impossibles.
    timeframe: str = Field(default="", max_length=8)
    entry_type: EntryType = Field(default=EntryType.MARKET)
    entry: float
    stop_loss: float
    # Nombre de decimales du broker pour cet instrument : l'affichage doit
    # montrer exactement la precision cotee, ni plus ni moins.
    digits: int = Field(default=5)
    take_profit_1: float | None = Field(default=None)
    take_profit_2: float | None = Field(default=None)
    take_profit_3: float | None = Field(default=None)

    risk_distance: float = Field(default=0.0)
    risk_reward_1: float | None = Field(default=None)
    risk_reward_2: float | None = Field(default=None)
    risk_reward_3: float | None = Field(default=None)

    score: float = Field(default=0.0, index=True)
    score_breakdown: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    confidence: int = Field(default=0)

    timeframe_states: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    risks: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    context: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    invalidation: str | None = Field(default=None, sa_column=Column(Text))

    # L'IA commente, elle ne decide pas et n'invente aucun prix.
    ai_comment: str | None = Field(default=None, sa_column=Column(Text))
    ai_provider: str | None = Field(default=None, max_length=64)

    strategy_version: str = Field(default=STRATEGY_VERSION, max_length=64)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    published_at: datetime | None = Field(default=None)
    telegram_message_id: int | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    closed_at: datetime | None = Field(default=None)

    # Resultat mesure, renseigne par la boucle de suivi. ``None`` tant que le
    # signal vit : jamais de resultat suppose.
    result_r: float | None = Field(default=None)
    max_favorable_r: float = Field(default=0.0)
    max_adverse_r: float = Field(default=0.0)

    # Fraction deja encaissee, en unites de risque, et part encore ouverte.
    # Sans ces deux champs le suivi mesure « sur position entiere » alors que
    # le courtier a ferme 40 % a TP1 : il inscrit -1 R sur une operation qui
    # avait protege son gain.
    booked_r: float = Field(default=0.0)
    open_fraction: float = Field(default=1.0)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def targets(self) -> list[float]:
        """Les objectifs reellement definis, dans l'ordre."""
        return [
            value
            for value in (self.take_profit_1, self.take_profit_2, self.take_profit_3)
            if value is not None
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "brokerSymbol": self.broker_symbol,
            "direction": self.direction.value,
            "decision": self.decision.value,
            "status": self.status.value,
            "timeframe": self.timeframe,
            "entryType": self.entry_type.value,
            "entry": self.entry,
            "stopLoss": self.stop_loss,
            "digits": self.digits,
            "takeProfit1": self.take_profit_1,
            "takeProfit2": self.take_profit_2,
            "takeProfit3": self.take_profit_3,
            "riskDistance": self.risk_distance,
            "riskReward1": self.risk_reward_1,
            "riskReward2": self.risk_reward_2,
            "riskReward3": self.risk_reward_3,
            "score": round(self.score, 1),
            "scoreBreakdown": dict(self.score_breakdown),
            "confidence": self.confidence,
            "timeframes": dict(self.timeframe_states),
            "reasons": list(self.reasons),
            "risks": list(self.risks),
            "invalidation": self.invalidation,
            "aiComment": self.ai_comment,
            "aiProvider": self.ai_provider,
            "strategyVersion": self.strategy_version,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "publishedAt": self.published_at.isoformat() if self.published_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "closedAt": self.closed_at.isoformat() if self.closed_at else None,
            "resultR": self.result_r,
            "maxFavorableR": round(self.max_favorable_r, 2),
            "maxAdverseR": round(self.max_adverse_r, 2),
        }


class WatcherSignalEvent(SQLModel, table=True):
    """Evenement du cycle de vie d'un signal (CDC3 section 32)."""

    __tablename__ = "watcher_signal_events"

    id: int | None = Field(default=None, primary_key=True)
    signal_id: int = Field(index=True, foreign_key="watcher_signals.id")
    kind: WatcherStatus
    price: float | None = Field(default=None)
    detail: str | None = Field(default=None, max_length=500)
    published: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "signalId": self.signal_id,
            "kind": self.kind.value,
            "price": self.price,
            "detail": self.detail,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class WatcherPostMortem(SQLModel, table=True):
    """Analyse d'une perte, pour ne pas la reproduire (CDC3 section 41).

    Une table a part, et non un ``WatcherSignalEvent`` : les evenements
    tracent des transitions, pas des analyses. L'unicite sur ``signal_id``
    garantit qu'une perte n'est comptee qu'une fois, meme si le suivi repasse
    sur un signal deja clos.
    """

    __tablename__ = "watcher_post_mortems"

    id: int | None = Field(default=None, primary_key=True)
    signal_id: int = Field(foreign_key="watcher_signals.id", unique=True, index=True)
    symbol: str = Field(max_length=32, index=True)
    direction: Direction
    entry_type: EntryType
    timeframe: str = Field(max_length=8)
    score: float = Field(default=0.0)
    # Sur quoi la decision s'appuyait, et ce qu'elle a ignore.
    criteria_high: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    criteria_low: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    max_favorable_r: float = Field(default=0.0)
    max_adverse_r: float = Field(default=0.0)
    result_r: float | None = Field(default=None)
    session_hour: int = Field(default=0)
    # La position reelle, quand il y en a eu une : c'est elle qui dit ce que
    # l'argent a fait. Nulle si aucun ordre n'est parti.
    trade_id: int | None = Field(default=None, index=True)
    trade_pnl: float | None = Field(default=None)
    lesson: str | None = Field(default=None, max_length=300)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class WatcherAnalysis(SQLModel, table=True):
    """Trace de chaque analyse, publiee ou non (CDC3 sections 69 et 82).

    Sert a deux choses precises : reconnaitre qu'un instrument deja en WATCH
    vient de franchir sa confirmation, et comparer plus tard les scores aux
    resultats reels pour une calibration honnete.
    """

    __tablename__ = "watcher_analyses"

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=32)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    decision: WatcherDecision = Field(default=WatcherDecision.NO_TRADE)
    score: float = Field(default=0.0)
    bias: str = Field(default="NEUTRAL", max_length=16)
    price: float | None = Field(default=None)
    volatility: VolatilityLevel = Field(default=VolatilityLevel.UNKNOWN)
    risk_verdict: RiskVerdict = Field(default=RiskVerdict.WAIT)
    blocked_reason: str | None = Field(default=None, max_length=300)
    signal_id: int | None = Field(default=None)
    watch_trigger: str | None = Field(default=None, max_length=200)
    # Vrai quand une alerte WATCH a reellement ete envoyee pour cette analyse :
    # c'est ce drapeau qui empeche de repeter la meme alerte a chaque tour.
    alert_sent: bool = Field(default=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "decision": self.decision.value,
            "score": round(self.score, 1),
            "bias": self.bias,
            "price": self.price,
            "volatility": self.volatility.value,
            "riskVerdict": self.risk_verdict.value,
            "blockedReason": self.blocked_reason,
            "signalId": self.signal_id,
            "watchTrigger": self.watch_trigger,
            "alertSent": self.alert_sent,
        }


# Les modeles du watcher sont importes apres ``app.models`` : la normalisation
# faite la-bas ne les a pas vus. On la rejoue ici, elle est idempotente.
normalize_datetime_columns(SQLModel.metadata)

__all__ = [
    "OPEN_STATUSES",
    "STRATEGY_VERSION",
    "TERMINAL_STATUSES",
    "EntryType",
    "RiskVerdict",
    "VolatilityLevel",
    "VolumeKind",
    "WatcherAnalysis",
    "WatcherDecision",
    "WatcherPostMortem",
    "WatcherSignal",
    "WatcherSignalEvent",
    "WatcherStatus",
]
