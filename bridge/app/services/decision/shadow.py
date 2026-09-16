"""Shadow mode : decider sans envoyer d'ordre (CDC2 sections 84 et 85).

Le systeme analyse, tranche, et enregistre ce qu'il AURAIT fait. Rien ne part
au broker. C'est le seul moyen honnete de juger une intelligence avant de lui
confier de l'argent : la comparaison porte sur des decisions reellement
prises, pas sur une reconstitution a posteriori.

Toutes les statistiques renvoient ``None`` quand la mesure n'a pas de sens
(aucun trade cloture, aucune perte pour un profit factor) : aucune valeur
n'est inventee pour remplir un tableau.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from app.models.enums import Direction
from app.models.intelligence import (
    DecisionAction,
    DecisionSource,
    ShadowOutcome,
    ShadowTrade,
)
from app.services.decision.engine import DecisionOutcome
from app.services.decision.inputs import TradeLevels


class ShadowEngine(StrEnum):
    """Origine intellectuelle d'une decision simulee (CDC2 section 85)."""

    LOCAL_AI = "LOCAL_AI"
    OPENROUTER = "OPENROUTER"
    ENSEMBLE = "ENSEMBLE"
    TELEGRAM = "TELEGRAM"
    UNKNOWN = "UNKNOWN"


ENGINE_LABELS: dict[ShadowEngine, str] = {
    ShadowEngine.LOCAL_AI: "IA locale",
    ShadowEngine.OPENROUTER: "OpenRouter",
    ShadowEngine.ENSEMBLE: "Ensemble",
    ShadowEngine.TELEGRAM: "Telegram",
    ShadowEngine.UNKNOWN: "Origine inconnue",
}

_OUTCOME_BY_ACTION: dict[DecisionAction, ShadowOutcome] = {
    DecisionAction.STRONG_BUY: ShadowOutcome.WOULD_BUY,
    DecisionAction.BUY: ShadowOutcome.WOULD_BUY,
    DecisionAction.STRONG_SELL: ShadowOutcome.WOULD_SELL,
    DecisionAction.SELL: ShadowOutcome.WOULD_SELL,
}


def outcome_for(action: DecisionAction) -> ShadowOutcome:
    """WAIT, NO_TRADE et NEEDS_REVIEW se traduisent par WOULD_SKIP."""
    return _OUTCOME_BY_ACTION.get(action, ShadowOutcome.WOULD_SKIP)


def build_shadow_trade(
    outcome: DecisionOutcome,
    levels: TradeLevels | None = None,
    *,
    decision_id: int | None = None,
    volume: float | None = None,
) -> ShadowTrade:
    """Trace de ce que le systeme aurait fait, sans aucun ordre envoye.

    ``volume`` provient du RiskManager quand il a pu etre calcule ; il reste
    ``None`` sinon. Un WOULD_SKIP ne porte jamais de niveaux.
    """
    shadow_outcome = outcome_for(outcome.action)
    if shadow_outcome is ShadowOutcome.WOULD_SKIP:
        levels = None

    return ShadowTrade(
        decision_id=decision_id,
        symbol=outcome.symbol,
        outcome=shadow_outcome,
        direction=outcome.direction if shadow_outcome is not ShadowOutcome.WOULD_SKIP else None,
        entry_price=levels.entry_price if levels else None,
        stop_loss=levels.stop_loss if levels else None,
        take_profit=levels.take_profits[0] if levels and levels.take_profits else None,
        volume=volume,
        source=outcome.source,
    )


# Largeur de la bande mesuree sous le seuil de confiance. Un dixieme : c'est
# exactement ce que cinq pas du regleur ouvriraient, donc ce qu'il faut avoir
# mesure avant de le laisser descendre. Plus large, on melangerait des
# qualites trop differentes pour conclure.
MARGINAL_MARGIN = 0.10


def marginal_context(context: Any) -> Any:
    """Le meme contexte, avec l'exigence de confiance abaissee d'un cran.

    Rejouer la decision avec ce contexte repond a une question precise :
    « cette opportunite passait-elle, au seuil d'en dessous ? ». Si oui, le
    seuil etait le SEUL obstacle, et elle merite d'etre mesuree. Si non, autre
    chose la refusait et elle n'apprendrait rien sur le seuil.
    """
    return replace(
        context, min_confidence=max(0.0, float(context.min_confidence) - MARGINAL_MARGIN)
    )


def close_shadow_trade(trade: ShadowTrade, close_price: float) -> ShadowTrade:
    """Cloture une simulation et calcule son R, sans jamais l'estimer.

    Sans entree ni stop, le R reste ``None`` : la simulation est conservee
    mais n'entre dans aucune statistique.
    """
    trade.close_price = close_price
    if trade.entry_price is None or trade.stop_loss is None or trade.direction is None:
        trade.r_multiple = None
        trade.result = "UNDETERMINED"
        return trade

    risk = abs(trade.entry_price - trade.stop_loss)
    if risk <= 0:
        trade.r_multiple = None
        trade.result = "UNDETERMINED"
        return trade

    move = close_price - trade.entry_price
    if trade.direction is Direction.SELL:
        move = -move
    trade.r_multiple = round(move / risk, 4)
    trade.result = "WIN" if trade.r_multiple > 0 else ("LOSS" if trade.r_multiple < 0 else "FLAT")
    return trade


@dataclass(slots=True)
class ShadowStats:
    """Statistiques comparees d'un lot de decisions simulees."""

    simulated: int = 0
    skipped: int = 0
    closed: int = 0
    wins: int = 0
    losses: int = 0
    flat: int = 0
    win_rate: float | None = None
    loss_rate: float | None = None
    average_r: float | None = None
    total_r: float | None = None
    max_drawdown_r: float | None = None
    profit_factor: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulated": self.simulated,
            "skipped": self.skipped,
            "closed": self.closed,
            "wins": self.wins,
            "losses": self.losses,
            "flat": self.flat,
            "winRate": self.win_rate,
            "lossRate": self.loss_rate,
            "averageR": self.average_r,
            "totalR": self.total_r,
            "maxDrawdownR": self.max_drawdown_r,
            "profitFactor": self.profit_factor,
        }


@dataclass(slots=True)
class ShadowReport:
    """Vue globale plus ventilations par source et par moteur."""

    overall: ShadowStats = field(default_factory=ShadowStats)
    by_source: dict[DecisionSource, ShadowStats] = field(default_factory=dict)
    by_engine: dict[ShadowEngine, ShadowStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.to_dict(),
            "bySource": {
                source.value: stats.to_dict() for source, stats in self.by_source.items()
            },
            "byEngine": {
                engine.value: {"label": ENGINE_LABELS[engine], **stats.to_dict()}
                for engine, stats in self.by_engine.items()
            },
        }


def compute_stats(trades: Iterable[ShadowTrade]) -> ShadowStats:
    """Agrege un lot de simulations. Aucune extrapolation."""
    stats = ShadowStats()
    r_values: list[float] = []

    for trade in trades:
        if trade.outcome is ShadowOutcome.WOULD_SKIP:
            stats.skipped += 1
            continue
        stats.simulated += 1
        if trade.r_multiple is None:
            continue
        stats.closed += 1
        r_values.append(float(trade.r_multiple))
        if trade.r_multiple > 0:
            stats.wins += 1
        elif trade.r_multiple < 0:
            stats.losses += 1
        else:
            stats.flat += 1

    if not r_values:
        return stats

    stats.win_rate = round(stats.wins / stats.closed, 4)
    stats.loss_rate = round(stats.losses / stats.closed, 4)
    stats.total_r = round(sum(r_values), 4)
    stats.average_r = round(sum(r_values) / len(r_values), 4)
    stats.max_drawdown_r = _max_drawdown(r_values)

    gains = sum(value for value in r_values if value > 0)
    pertes = abs(sum(value for value in r_values if value < 0))
    # Sans aucune perte, le profit factor n'a pas de valeur finie : on n'en
    # invente pas une.
    stats.profit_factor = round(gains / pertes, 4) if pertes > 0 else None
    return stats


def _max_drawdown(r_values: Sequence[float]) -> float:
    """Plus forte baisse de la courbe cumulee, exprimee en R (valeur positive)."""
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in r_values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return round(abs(worst), 4)


def build_report(
    trades: Sequence[ShadowTrade],
    engine_by_decision: Mapping[int, ShadowEngine] | None = None,
) -> ShadowReport:
    """Rapport complet : global, par source, par moteur (CDC2 section 85)."""
    report = ShadowReport(overall=compute_stats(trades))

    by_source: dict[DecisionSource, list[ShadowTrade]] = {}
    for trade in trades:
        by_source.setdefault(trade.source, []).append(trade)
    report.by_source = {source: compute_stats(items) for source, items in by_source.items()}

    mapping = engine_by_decision or {}
    by_engine: dict[ShadowEngine, list[ShadowTrade]] = {}
    for trade in trades:
        engine = _engine_of(trade, mapping)
        by_engine.setdefault(engine, []).append(trade)
    report.by_engine = {engine: compute_stats(items) for engine, items in by_engine.items()}
    return report


def _engine_of(trade: ShadowTrade, mapping: Mapping[int, ShadowEngine]) -> ShadowEngine:
    if trade.source is DecisionSource.TELEGRAM:
        return ShadowEngine.TELEGRAM
    if trade.decision_id is not None and trade.decision_id in mapping:
        return mapping[trade.decision_id]
    return ShadowEngine.UNKNOWN


__all__ = [
    "ENGINE_LABELS",
    "MARGINAL_MARGIN",
    "ShadowEngine",
    "ShadowReport",
    "ShadowStats",
    "build_report",
    "build_shadow_trade",
    "close_shadow_trade",
    "compute_stats",
    "marginal_context",
    "outcome_for",
]
