"""Registre des strategies actives (CDC2 section 45).

Seules les strategies reellement implementees et couvertes par des tests sont
enregistrees. En ajouter une sans test revient a faire confiance a du code
jamais verifie : le registre refuse une strategie desactivee.

En cas de propositions contradictoires de qualite comparable, le registre ne
tranche pas : il rend ``None``. Le doute se traduit par l'absence de trade
(CDC2 section 113).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from app.config.logging_config import get_logger
from app.models.intelligence import MarketRegime
from app.services.decision.inputs import AnalysisBundle, PriceStructure
from app.services.strategies.base import StrategyProposal, TradingStrategy
from app.services.strategies.families import (
    BreakoutStrategy,
    MeanReversionStrategy,
    PullbackStrategy,
    TrendFollowingStrategy,
)

logger = get_logger(__name__)

# Ecart de score en dessous duquel deux propositions opposees se neutralisent.
AMBIGUITY_GAP = 0.10


def default_strategies() -> list[TradingStrategy]:
    """Strategies implementees et testees a ce jour."""
    return [
        TrendFollowingStrategy(),
        PullbackStrategy(),
        BreakoutStrategy(),
        MeanReversionStrategy(),
    ]


class StrategyRegistry:
    """Catalogue interrogeable des strategies."""

    def __init__(self, strategies: Iterable[TradingStrategy] | None = None) -> None:
        self._strategies: list[TradingStrategy] = []
        for strategy in strategies if strategies is not None else default_strategies():
            self.register(strategy)

    # ------------------------------------------------------------------
    def register(self, strategy: TradingStrategy) -> None:
        """Ajoute une strategie active. Une strategie inactive est ignoree."""
        if not strategy.enabled:
            logger.info("Strategie %s ignoree : non activee", strategy.name)
            return
        if any(existing.name == strategy.name for existing in self._strategies):
            raise ValueError(f"Stratégie déjà enregistrée : {strategy.name}")
        self._strategies.append(strategy)

    @property
    def strategies(self) -> list[TradingStrategy]:
        return list(self._strategies)

    def get(self, name: str) -> TradingStrategy | None:
        return next((item for item in self._strategies if item.name == name), None)

    def for_regime(self, regime: MarketRegime | None) -> list[TradingStrategy]:
        return [item for item in self._strategies if item.applies_to(regime)]

    def describe(self) -> list[dict[str, Any]]:
        return [item.describe() for item in self._strategies]

    # ------------------------------------------------------------------
    def evaluate(
        self, bundle: AnalysisBundle, structure: PriceStructure
    ) -> list[StrategyProposal]:
        """Toutes les propositions, de la meilleure a la moins bonne."""
        proposals: list[StrategyProposal] = []
        for strategy in self._strategies:
            proposal = strategy.propose(bundle, structure)
            if proposal is not None:
                proposals.append(proposal)
        proposals.sort(key=lambda item: item.score, reverse=True)
        return proposals

    def best(
        self, bundle: AnalysisBundle, structure: PriceStructure
    ) -> StrategyProposal | None:
        """Meilleure proposition, sauf si deux strategies se contredisent."""
        proposals = self.evaluate(bundle, structure)
        return select_best(proposals)


def select_best(proposals: Sequence[StrategyProposal]) -> StrategyProposal | None:
    """Retient la tete de classement, sauf contradiction non tranchee."""
    if not proposals:
        return None
    leader = proposals[0]
    for challenger in proposals[1:]:
        if challenger.direction is leader.direction:
            continue
        if leader.score - challenger.score < AMBIGUITY_GAP:
            logger.info(
                "Strategies contradictoires (%s vs %s) : aucune proposition retenue",
                leader.strategy,
                challenger.strategy,
            )
            return None
    return leader


strategy_registry = StrategyRegistry()

__all__ = [
    "AMBIGUITY_GAP",
    "StrategyRegistry",
    "default_strategies",
    "select_best",
    "strategy_registry",
]
