"""Socle des strategies de trading (CDC2 section 45).

Une strategie repond a une seule question : « dans ce contexte, ce marche
offre-t-il un setup de ma famille, et dans quel sens ? ». Elle ne calcule
aucun prix — les niveaux viennent du planificateur deterministe — et elle ne
decide pas d'executer : c'est le role du moteur de decision.

Chaque strategie declare les regimes de marche ou elle a un sens. Hors de ces
regimes, elle ne propose rien : une strategie de suivi de tendance n'a rien a
dire dans un range.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.models.enums import Direction
from app.models.intelligence import MarketRegime
from app.services.decision.inputs import AnalysisBundle, PriceStructure


class StrategyFamily(StrEnum):
    """Familles prevues par le CDC2 section 45."""

    TREND_FOLLOWING = "TREND_FOLLOWING"
    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
    MEAN_REVERSION = "MEAN_REVERSION"


FAMILY_LABELS: dict[StrategyFamily, str] = {
    StrategyFamily.TREND_FOLLOWING: "Suivi de tendance",
    StrategyFamily.BREAKOUT: "Cassure",
    StrategyFamily.PULLBACK: "Repli dans la tendance",
    StrategyFamily.MEAN_REVERSION: "Retour à la moyenne",
}


@dataclass(slots=True)
class StrategyProposal:
    """Setup identifie par une strategie, avant toute decision."""

    strategy: str
    family: StrategyFamily
    direction: Direction
    score: float
    reasons: list[str] = field(default_factory=list)
    negative_factors: list[str] = field(default_factory=list)
    regime: MarketRegime | None = None

    def __post_init__(self) -> None:
        self.score = max(0.0, min(1.0, float(self.score)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "family": self.family.value,
            "familyLabel": FAMILY_LABELS[self.family],
            "direction": self.direction.value,
            "score": round(self.score, 4),
            "reasons": list(self.reasons),
            "negativeFactors": list(self.negative_factors),
            "regime": self.regime.value if self.regime else None,
        }


class TradingStrategy(ABC):
    """Contrat commun a toutes les strategies."""

    name: str = "strategy"
    family: StrategyFamily = StrategyFamily.TREND_FOLLOWING
    regimes: frozenset[MarketRegime] = frozenset()
    # Une strategie n'est activee que si elle est reellement implementee ET
    # couverte par des tests (CDC2 section 45).
    enabled: bool = False

    def applies_to(self, regime: MarketRegime | None) -> bool:
        """Sans regime identifie, aucune strategie ne s'applique."""
        if not self.enabled or regime is None:
            return False
        return regime in self.regimes

    @abstractmethod
    def evaluate(
        self, bundle: AnalysisBundle, structure: PriceStructure
    ) -> StrategyProposal | None:
        """Rend une proposition, ou ``None`` si le setup n'est pas la."""

    # ------------------------------------------------------------------
    def propose(
        self, bundle: AnalysisBundle, structure: PriceStructure
    ) -> StrategyProposal | None:
        """Point d'entree : verifie le regime et la structure avant d'evaluer."""
        if not self.applies_to(bundle.market_regime):
            return None
        if not structure.usable:
            return None
        proposal = self.evaluate(bundle, structure)
        if proposal is not None and proposal.regime is None:
            proposal.regime = bundle.market_regime
        return proposal

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "family": self.family.value,
            "familyLabel": FAMILY_LABELS[self.family],
            "enabled": self.enabled,
            "regimes": sorted(regime.value for regime in self.regimes),
        }


def technical_strength(bundle: AnalysisBundle, fallback: float = 0.5) -> float:
    """Note technique disponible, sinon une base neutre explicite.

    Le repli n'est pas une valeur inventee : il sert uniquement a classer les
    propositions entre elles. L'absence reelle de donnee technique est
    signalee separement au moteur de confiance, qui la compte comme absente.
    """
    technical = bundle.technical
    if technical is None or technical.score is None:
        return fallback
    return max(0.0, min(1.0, float(technical.score)))


__all__ = [
    "FAMILY_LABELS",
    "StrategyFamily",
    "StrategyProposal",
    "TradingStrategy",
    "technical_strength",
]
