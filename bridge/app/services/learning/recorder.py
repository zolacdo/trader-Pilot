"""Memoire d'apprentissage : ce que chaque trade a reellement donne (CDC2 49).

Apres chaque trade, le systeme enregistre le contexte complet : origine de la
decision, scores, strategie, niveaux, risque, resultat, MFE, MAE, duree,
regime, session, modeles IA utilises et consensus obtenu.

REGLE ABSOLUE : le systeme ne reecrit JAMAIS ses propres regles. Il produit
des statistiques ; un humain lit, decide et modifie la configuration. Aucune
fonction de ce module ne modifie un parametre de trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.models.enums import Direction, EventLevel
from app.models.intelligence import (
    ConsensusOutcome,
    DecisionAction,
    DecisionSource,
    MarketRegime,
    StrategyPerformance,
)
from app.repositories import journal_repo, pattern_repo
from app.services import journal

# Le moteur d'apprentissage n'a pas le droit de modifier la configuration.
AUTOMATIC_RULE_UPDATES = False

LEARNING_CATEGORY = "learning"
LEARNING_EVENT = "trade_outcome"
UNSPECIFIED_STRATEGY = "NON_SPECIFIEE"

LEARNING_NOTE = (
    "Statistiques d'apprentissage : le système mesure et présente, il ne modifie "
    "jamais ses propres règles. Toute évolution de configuration reste une décision humaine."
)

WIN = "WIN"
LOSS = "LOSS"
BREAKEVEN = "BREAKEVEN"


@dataclass(slots=True)
class TradeLearningRecord:
    """Contexte complet d'un trade termine. Une donnee absente reste None."""

    symbol: str
    direction: Direction
    source: DecisionSource = DecisionSource.AI_GENERATED
    strategy: str | None = None
    decision: DecisionAction | None = None

    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    take_profits: list[float] = field(default_factory=list)
    volume: float | None = None
    risk_amount: float | None = None
    risk_percent: float | None = None

    result: str | None = None
    realized_pnl: float | None = None
    r_multiple: float | None = None
    mfe: float | None = None
    mae: float | None = None
    duration_minutes: float | None = None

    regime: MarketRegime | None = None
    session_name: str | None = None
    ai_models: list[str] = field(default_factory=list)
    ai_consensus: ConsensusOutcome | None = None
    scores: dict[str, float | None] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    trade_id: int | None = None
    decision_id: int | None = None
    signal_id: int | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None

    @property
    def strategy_key(self) -> str:
        return self.strategy or UNSPECIFIED_STRATEGY

    @property
    def day(self) -> str:
        moment = self.closed_at or self.opened_at or utcnow()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.date().isoformat()

    def derived_result(self) -> str | None:
        """Resultat declare, sinon deduit du PnL. Jamais invente."""
        if self.result:
            return self.result.upper()
        if self.realized_pnl is None:
            return None
        if self.realized_pnl > 0:
            return WIN
        if self.realized_pnl < 0:
            return LOSS
        return BREAKEVEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "source": self.source.value,
            "strategy": self.strategy_key,
            "decision": self.decision.value if self.decision else None,
            "entryPrice": self.entry_price,
            "stopLoss": self.stop_loss,
            "takeProfit": self.take_profit,
            "takeProfits": list(self.take_profits),
            "volume": self.volume,
            "riskAmount": self.risk_amount,
            "riskPercent": self.risk_percent,
            "result": self.derived_result(),
            "realizedPnl": self.realized_pnl,
            "rMultiple": self.r_multiple,
            "mfe": self.mfe,
            "mae": self.mae,
            "durationMinutes": self.duration_minutes,
            "regime": self.regime.value if self.regime else None,
            "session": self.session_name,
            "aiModels": list(self.ai_models),
            "aiConsensus": self.ai_consensus.value if self.ai_consensus else None,
            "scores": dict(self.scores),
            "context": dict(self.context),
            "tradeId": self.trade_id,
            "decisionId": self.decision_id,
            "signalId": self.signal_id,
            "openedAt": self.opened_at.isoformat() if self.opened_at else None,
            "closedAt": self.closed_at.isoformat() if self.closed_at else None,
        }


def _summarise(record: TradeLearningRecord) -> str:
    result = record.derived_result() or "résultat inconnu"
    pieces = [f"Trade {record.symbol} {record.direction.value} clôturé : {result}"]
    if record.r_multiple is not None:
        pieces.append(f"{record.r_multiple:+.2f}R")
    if record.realized_pnl is not None:
        pieces.append(f"PnL {record.realized_pnl:+.2f}")
    pieces.append(f"stratégie {record.strategy_key}")
    return ", ".join(pieces) + "."


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Agregat d'une journee pour une strategie et une origine donnees."""
    ordered = sorted(rows, key=lambda row: row.get("closedAt") or row.get("openedAt") or "")
    trades = len(ordered)
    wins = sum(1 for row in ordered if row.get("result") == WIN)
    losses = sum(1 for row in ordered if row.get("result") == LOSS)
    net_r = sum(row["rMultiple"] for row in ordered if row.get("rMultiple") is not None)
    net_pnl = sum(row["realizedPnl"] for row in ordered if row.get("realizedPnl") is not None)

    equity = 0.0
    peak = 0.0
    worst = 0.0
    for row in ordered:
        value = row.get("realizedPnl")
        if value is None:
            continue
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)

    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "net_r": round(net_r, 4),
        "net_pnl": round(net_pnl, 2),
        "max_drawdown": round(abs(worst), 2),
    }


async def collect_records(
    session: AsyncSession,
    day: str | None = None,
    strategy: str | None = None,
    source: DecisionSource | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Releve les enregistrements d'apprentissage stockes dans le journal."""
    since = None
    if day is not None:
        since = datetime.fromisoformat(day).replace(tzinfo=UTC) - timedelta(days=1)
    entries = await journal_repo.list_entries(
        session,
        limit=limit,
        category=LEARNING_CATEGORY,
        since=since,
    )
    rows: list[dict[str, Any]] = []
    for entry in entries:
        data = entry.data or {}
        if entry.event != LEARNING_EVENT or not data:
            continue
        if day is not None and data.get("day") != day:
            continue
        if strategy is not None and data.get("strategy") != strategy:
            continue
        if source is not None and data.get("source") != source.value:
            continue
        rows.append(data)
    return rows


async def record_trade_outcome(
    session: AsyncSession, record: TradeLearningRecord
) -> StrategyPerformance:
    """Enregistre un trade termine puis recalcule l'agregat de la journee.

    Le detail va dans le journal (consultable et exportable), l'agregat dans
    ``strategy_performance``. Aucune regle de trading n'est touchee.
    """
    await journal.record(
        session,
        event=LEARNING_EVENT,
        message=_summarise(record),
        level=EventLevel.INFO,
        category=LEARNING_CATEGORY,
        signal_id=record.signal_id,
        data=record.to_dict(),
    )
    rows = await collect_records(
        session, day=record.day, strategy=record.strategy_key, source=record.source
    )
    return await pattern_repo.upsert_strategy_performance(
        session,
        day=record.day,
        strategy=record.strategy_key,
        source=record.source,
        values=aggregate(rows),
    )


__all__ = [
    "AUTOMATIC_RULE_UPDATES",
    "BREAKEVEN",
    "LEARNING_CATEGORY",
    "LEARNING_EVENT",
    "LEARNING_NOTE",
    "LOSS",
    "UNSPECIFIED_STRATEGY",
    "WIN",
    "TradeLearningRecord",
    "aggregate",
    "collect_records",
    "record_trade_outcome",
]
