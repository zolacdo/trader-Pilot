"""Garde-fous : en cas de doute, NO TRADE (CDC2 section 113).

Chaque garde-fou repond a une seule question et rend un verdict lisible. Ils
s'executent tous, meme apres un premier blocage : l'utilisateur doit voir
toutes les raisons, pas seulement la premiere rencontree.

Aucun garde-fou ne peut etre contourne par un score de confiance eleve.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.models.intelligence import DecisionAction, NewsImpact
from app.services.confidence.engine import ConfidenceResult
from app.services.decision.context import DecisionContext


class GuardCode(StrEnum):
    """Motifs de blocage listes par le CDC2 section 113."""

    TRADING_DISABLED = "TRADING_DISABLED"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    INCONSISTENT_PRICE = "INCONSISTENT_PRICE"
    AI_DISAGREEMENT = "AI_DISAGREEMENT"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    NEWS_NOT_ANALYSABLE = "NEWS_NOT_ANALYSABLE"
    NEWS_BLACKOUT = "NEWS_BLACKOUT"
    MT5_UNSTABLE = "MT5_UNSTABLE"
    INCOMPLETE_SIGNAL = "INCOMPLETE_SIGNAL"
    RISK_NOT_COMPUTABLE = "RISK_NOT_COMPUTABLE"
    INVALID_STOP_LOSS = "INVALID_STOP_LOSS"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INSUFFICIENT_ANALYSIS = "INSUFFICIENT_ANALYSIS"
    NO_DIRECTION = "NO_DIRECTION"


@dataclass(slots=True)
class GuardVerdict:
    """Un garde-fou declenche, avec son message destine a l'utilisateur."""

    code: GuardCode
    message: str
    action: DecisionAction = DecisionAction.NO_TRADE

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "action": self.action.value}


GuardFunction = Callable[[DecisionContext, ConfidenceResult], GuardVerdict | None]


# ---------------------------------------------------------------------------
# Garde-fous individuels
# ---------------------------------------------------------------------------

def _trading_disabled(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    if context.trading_enabled:
        return None
    return GuardVerdict(
        GuardCode.TRADING_DISABLED,
        "Le trading automatique est désactivé pour cette source.",
    )


def _circuit_breaker(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    state = context.breaker
    if state is None or not state.tripped:
        return None
    return GuardVerdict(
        GuardCode.CIRCUIT_BREAKER,
        f"Coupe-circuit actif : {state.summary}",
    )


def _stale_market_data(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    quote = context.analysis.quote
    if quote is None:
        return GuardVerdict(
            GuardCode.STALE_MARKET_DATA,
            "Aucune cotation disponible : impossible de décider sur un prix inconnu.",
        )
    age = quote.age_seconds(context.now)
    if age is None:
        return GuardVerdict(
            GuardCode.STALE_MARKET_DATA,
            "La cotation reçue n'est pas horodatée : sa fraîcheur est invérifiable.",
        )
    if age > context.max_quote_age_seconds:
        return GuardVerdict(
            GuardCode.STALE_MARKET_DATA,
            f"Données de marché trop anciennes : {age:.0f} secondes "
            f"(limite {context.max_quote_age_seconds:.0f} s).",
        )
    return None


def _inconsistent_price(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    quote = context.analysis.quote
    if quote is None or quote.consistent:
        return None
    return GuardVerdict(
        GuardCode.INCONSISTENT_PRICE,
        "Prix incohérent : le bid, l'ask ou leur écart sont invalides.",
    )


def _ai_state(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    consensus = context.analysis.consensus
    if consensus is None:
        if context.consensus_required:
            return GuardVerdict(
                GuardCode.AI_UNAVAILABLE,
                "Consensus IA exigé mais aucune analyse n'a été produite.",
                action=DecisionAction.NEEDS_REVIEW,
            )
        return None

    contradicts = (
        consensus.direction is not None
        and context.direction is not None
        and consensus.direction is not context.direction
    )
    if contradicts:
        return GuardVerdict(
            GuardCode.AI_DISAGREEMENT,
            "Les intelligences contredisent la direction envisagée : aucun trade.",
        )

    if not context.consensus_required:
        return None

    if not consensus.available:
        return GuardVerdict(
            GuardCode.AI_UNAVAILABLE,
            "Consensus IA exigé mais indisponible : décision remise à une revue manuelle.",
            action=DecisionAction.NEEDS_REVIEW,
        )
    if consensus.blocks_auto_trade:
        return GuardVerdict(
            GuardCode.AI_DISAGREEMENT,
            f"Désaccord ou données insuffisantes côté IA : {consensus.detail or 'sans détail'}.",
        )
    if consensus.needs_manual_review:
        return GuardVerdict(
            GuardCode.AI_DISAGREEMENT,
            "Accord partiel des intelligences : une revue manuelle est nécessaire.",
            action=DecisionAction.NEEDS_REVIEW,
        )
    return None


def _news(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    news = context.analysis.news
    if news is None:
        return None
    if not news.analysable:
        return GuardVerdict(
            GuardCode.NEWS_NOT_ANALYSABLE,
            "Actualité critique non analysable : le contexte reste incertain.",
        )
    if news.blackout:
        detail = news.detail or "fenêtre d'actualité à fort impact"
        if news.minutes_to_event is not None:
            detail = f"{detail} ({news.minutes_to_event} minutes)"
        return GuardVerdict(GuardCode.NEWS_BLACKOUT, f"Blackout actualités : {detail}.")
    if news.impact is NewsImpact.CRITICAL:
        return GuardVerdict(
            GuardCode.NEWS_BLACKOUT,
            "Actualité d'impact critique en cours sur cet instrument.",
        )
    return None


def _mt5(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    if context.mt5_connected and context.mt5_stable:
        return None
    return GuardVerdict(
        GuardCode.MT5_UNSTABLE,
        "MetaTrader 5 est déconnecté ou instable : aucun ordre ne peut être fiable.",
    )


def _signal_complete(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    if context.signal_complete:
        return None
    return GuardVerdict(
        GuardCode.INCOMPLETE_SIGNAL,
        "Signal incomplet : une information indispensable manque.",
    )


def _risk(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    if context.risk_computable:
        return None
    return GuardVerdict(
        GuardCode.RISK_NOT_COMPUTABLE,
        "Risque incalculable : taille de position impossible à déterminer.",
    )


def _levels(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    levels = context.levels
    if levels is None:
        return GuardVerdict(
            GuardCode.INVALID_STOP_LOSS,
            "Aucun plan de trade calculé : entrée, stop et cibles manquent.",
        )
    if not levels.valid:
        return GuardVerdict(
            GuardCode.INVALID_STOP_LOSS,
            "Stop loss invalide : il n'est pas du bon côté de l'entrée ou trop proche.",
        )
    return None


def _direction(context: DecisionContext, _: ConfidenceResult) -> GuardVerdict | None:
    if context.direction is not None:
        return None
    return GuardVerdict(
        GuardCode.NO_DIRECTION,
        "Aucune direction ne se dégage : les lectures se neutralisent.",
    )


def _coverage(context: DecisionContext, confidence: ConfidenceResult) -> GuardVerdict | None:
    minimum = context.thresholds.minimum_coverage
    if confidence.coverage >= minimum:
        return None
    missing = ", ".join(item.value for item in confidence.missing) or "aucune"
    return GuardVerdict(
        GuardCode.INSUFFICIENT_ANALYSIS,
        f"Analyse trop partielle : {confidence.coverage:.0%} des composantes disponibles "
        f"(minimum {minimum:.0%}). Manquantes : {missing}.",
    )


def _confidence(context: DecisionContext, confidence: ConfidenceResult) -> GuardVerdict | None:
    """Plancher absolu de confiance.

    Au-dessus de ce plancher mais sous le seuil d'entree, la decision reste
    WAIT : c'est le moteur qui tranche, pas ce garde-fou (CDC2 section 2).
    """
    floor = context.thresholds.wait
    if confidence.score >= floor:
        return None
    return GuardVerdict(
        GuardCode.LOW_CONFIDENCE,
        f"Confiance insuffisante : {confidence.score:.0f}/100 pour un plancher de {floor:.0f}.",
    )


# Ordre d'evaluation : du plus structurel au plus circonstanciel.
GUARDS: tuple[GuardFunction, ...] = (
    _trading_disabled,
    _circuit_breaker,
    _stale_market_data,
    _inconsistent_price,
    _mt5,
    _signal_complete,
    _direction,
    _levels,
    _risk,
    _news,
    _ai_state,
    _coverage,
    _confidence,
)


def run_guards(
    context: DecisionContext,
    confidence: ConfidenceResult,
    guards: tuple[GuardFunction, ...] = GUARDS,
) -> list[GuardVerdict]:
    """Execute tous les garde-fous et rend la liste de ceux qui bloquent."""
    verdicts: list[GuardVerdict] = []
    for guard in guards:
        verdict = guard(context, confidence)
        if verdict is not None:
            verdicts.append(verdict)
    return verdicts


def worst_action(verdicts: list[GuardVerdict]) -> DecisionAction | None:
    """NO_TRADE l'emporte toujours sur NEEDS_REVIEW : la prudence prime."""
    if not verdicts:
        return None
    if any(verdict.action is DecisionAction.NO_TRADE for verdict in verdicts):
        return DecisionAction.NO_TRADE
    return DecisionAction.NEEDS_REVIEW


__all__ = [
    "GUARDS",
    "GuardCode",
    "GuardFunction",
    "GuardVerdict",
    "run_guards",
    "worst_action",
]
