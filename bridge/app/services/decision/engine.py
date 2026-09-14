"""Moteur de decision (CDC2 sections 42, 44 et 113).

Le moteur ne cherche pas un trade : il cherche a savoir si un trade se
justifie. La sortie la plus frequente d'un systeme sain est WAIT ou NO_TRADE,
et rester des heures sans rien ouvrir est un fonctionnement normal
(CDC2 section 2).

Trois etapes, toujours dans cet ordre :

 1. le moteur de confiance assemble ce qui est connu ;
 2. les garde-fous cherchent une raison de refuser ;
 3. seulement s'il n'y en a aucune, les seuils choisissent l'action.

Le score de confiance ne touche jamais a la taille de position
(CDC2 section 44) : le RiskManager garde autorite absolue sur le risque.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config.logging_config import get_logger
from app.models.enums import Direction
from app.models.intelligence import (
    DecisionAction,
    DecisionRecord,
    DecisionSource,
    MarketRegime,
)
from app.services.confidence.engine import ConfidenceEngine, ConfidenceResult
from app.services.confidence.weights import ConfidenceWeights
from app.services.decision.context import DecisionContext
from app.services.decision.guards import GuardVerdict, run_guards, worst_action

logger = get_logger(__name__)

# Actions qui autorisent un envoi d'ordre une fois ramenees a l'execution.
_EXECUTABLE: dict[DecisionAction, DecisionAction] = {
    DecisionAction.STRONG_BUY: DecisionAction.BUY,
    DecisionAction.BUY: DecisionAction.BUY,
    DecisionAction.STRONG_SELL: DecisionAction.SELL,
    DecisionAction.SELL: DecisionAction.SELL,
}


def position_risk_multiplier(confidence_score: float) -> float:
    """Facteur applique au risque en fonction de la confiance : toujours 1.

    CDC2 section 44 : meme a 99 % de confiance, le risque ne depasse jamais la
    limite du RiskManager. Cette fonction existe pour que la regle soit
    explicite et verifiable par un test, plutot que sous-entendue.
    """
    del confidence_score
    return 1.0


@dataclass(slots=True)
class DecisionOutcome:
    """Verdict complet, executable ou non, toujours explicable."""

    action: DecisionAction
    symbol: str
    source: DecisionSource
    direction: Direction | None
    confidence: ConfidenceResult
    reason: str
    positive_factors: list[str] = field(default_factory=list)
    negative_factors: list[str] = field(default_factory=list)
    guards: list[GuardVerdict] = field(default_factory=list)
    regime: MarketRegime | None = None
    strategy: str | None = None

    @property
    def executable_action(self) -> DecisionAction:
        """Action ramenee a BUY / SELL / NO_TRADE avant execution."""
        return _EXECUTABLE.get(self.action, DecisionAction.NO_TRADE)

    @property
    def tradable(self) -> bool:
        return self.executable_action is not DecisionAction.NO_TRADE

    @property
    def blocked(self) -> bool:
        return bool(self.guards)

    def to_record(
        self,
        *,
        signal_id: int | None = None,
        opportunity_id: int | None = None,
        snapshot_id: int | None = None,
        shadow: bool = False,
    ) -> DecisionRecord:
        """Ligne de journal, y compris pour un trade NON pris (CDC2 section 76)."""
        return DecisionRecord(
            symbol=self.symbol,
            source=self.source,
            action=self.action,
            direction=self.direction,
            global_score=round(self.confidence.score, 2),
            confidence=round(self.confidence.ratio, 4),
            regime=self.regime,
            reason=self.reason,
            positive_factors=list(self.positive_factors),
            negative_factors=list(self.negative_factors),
            signal_id=signal_id,
            opportunity_id=opportunity_id,
            snapshot_id=snapshot_id,
            executed=False,
            shadow=shadow,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "executableAction": self.executable_action.value,
            "symbol": self.symbol,
            "source": self.source.value,
            "direction": self.direction.value if self.direction else None,
            "regime": self.regime.value if self.regime else None,
            "strategy": self.strategy,
            "reason": self.reason,
            "positiveFactors": list(self.positive_factors),
            "negativeFactors": list(self.negative_factors),
            "guards": [guard.to_dict() for guard in self.guards],
            "confidence": self.confidence.to_dict(),
        }


class DecisionEngine:
    """Transforme un contexte en action motivee."""

    def __init__(self, confidence: ConfidenceEngine | None = None) -> None:
        self._confidence = confidence or ConfidenceEngine()

    @property
    def confidence_engine(self) -> ConfidenceEngine:
        return self._confidence

    def with_weights(self, weights: ConfidenceWeights) -> DecisionEngine:
        return DecisionEngine(self._confidence.with_weights(weights))

    # ------------------------------------------------------------------
    def decide(self, context: DecisionContext) -> DecisionOutcome:
        """Rend une action parmi les sept, avec ses raisons."""
        direction = context.direction
        # La source du dossier dit ce qui s'applique : une opportunite generee
        # par le systeme n'a pas de signal Telegram a attendre.
        components = context.analysis.components(direction, source=context.source)
        confidence = self._confidence.evaluate(components)

        verdicts = run_guards(context, confidence)
        positives = self._positive_factors(confidence)
        negatives = self._negative_factors(confidence, verdicts)

        blocked = worst_action(verdicts)
        if blocked is not None:
            reason = self._blocked_reason(verdicts)
            logger.info("Decision %s : %s — %s", context.symbol, blocked.value, reason)
            return DecisionOutcome(
                action=blocked,
                symbol=context.symbol,
                source=context.source,
                direction=direction,
                confidence=confidence,
                reason=reason,
                positive_factors=positives,
                negative_factors=negatives,
                guards=verdicts,
                regime=context.analysis.market_regime,
                strategy=context.strategy,
            )

        action = self._action_from_score(context, confidence, direction)
        reason = self._reason_for(action, confidence, context)
        logger.info("Decision %s : %s (%.0f/100)", context.symbol, action.value, confidence.score)
        return DecisionOutcome(
            action=action,
            symbol=context.symbol,
            source=context.source,
            direction=direction,
            confidence=confidence,
            reason=reason,
            positive_factors=positives,
            negative_factors=negatives,
            guards=[],
            regime=context.analysis.market_regime,
            strategy=context.strategy,
        )

    # ------------------------------------------------------------------
    # Seuils
    # ------------------------------------------------------------------
    @staticmethod
    def entry_threshold(context: DecisionContext) -> float:
        """Barre d'entree : la plus exigeante des deux configurations."""
        return max(context.thresholds.entry, context.min_confidence_score)

    def _action_from_score(
        self,
        context: DecisionContext,
        confidence: ConfidenceResult,
        direction: Direction | None,
    ) -> DecisionAction:
        if direction is None:
            return DecisionAction.WAIT

        score = confidence.score
        entry = self.entry_threshold(context)
        strong = max(context.thresholds.strong, entry)

        if score >= strong:
            return DecisionAction.STRONG_BUY if direction is Direction.BUY else DecisionAction.STRONG_SELL
        if score >= entry:
            return DecisionAction.BUY if direction is Direction.BUY else DecisionAction.SELL
        # Setup lisible mais pas assez convaincant : on attend, on ne force pas.
        return DecisionAction.WAIT

    # ------------------------------------------------------------------
    # Explications
    # ------------------------------------------------------------------
    @staticmethod
    def _blocked_reason(verdicts: list[GuardVerdict]) -> str:
        return " ".join(verdict.message for verdict in verdicts)[:1500]

    @staticmethod
    def _reason_for(
        action: DecisionAction, confidence: ConfidenceResult, context: DecisionContext
    ) -> str:
        score = f"{confidence.score:.0f}/100"
        if action is DecisionAction.WAIT:
            entry = DecisionEngine.entry_threshold(context)
            return (
                f"Score de {score}, sous le seuil d'entrée de {entry:.0f} : "
                "le setup est lisible mais pas assez convaincant. On attend."
            )
        strongest = confidence.strongest()
        appui = ", ".join(item.label.lower() for item in strongest) or "aucun appui dominant"
        return f"Score de {score}. Principaux appuis : {appui}."

    @staticmethod
    def _positive_factors(confidence: ConfidenceResult) -> list[str]:
        return [
            f"{item.label} : {item.score:.0f}/100 ({item.contribution:.1f} pts)"
            for item in confidence.strongest(limit=4)
        ]

    @staticmethod
    def _negative_factors(
        confidence: ConfidenceResult, verdicts: list[GuardVerdict]
    ) -> list[str]:
        negatives = [verdict.message for verdict in verdicts]
        negatives.extend(
            f"{item.label} : {item.score:.0f}/100" for item in confidence.weakest(limit=3)
        )
        for component in confidence.missing:
            negatives.append(f"Composante indisponible : {component.value}")
        return negatives


decision_engine = DecisionEngine()

__all__ = [
    "DecisionEngine",
    "DecisionOutcome",
    "decision_engine",
    "position_risk_multiplier",
]
