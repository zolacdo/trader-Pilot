"""Contexte complet soumis au moteur de decision.

Rassemble ce que le systeme sait au moment de trancher : lectures de marche,
plan de trade deterministe, etat de l'IA, etat du coupe-circuit et garde-fous
d'exploitation. Le moteur ne va rien chercher lui-meme : tout arrive ici, ce
qui rend chaque decision reproductible a l'identique dans un test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models.core import utcnow
from app.models.enums import Direction
from app.models.intelligence import DecisionSource
from app.services.decision.circuit_breaker import BreakerState
from app.services.decision.inputs import AnalysisBundle, TradeLevels


@dataclass(slots=True)
class DecisionThresholds:
    """Seuils de passage d'une action a l'autre, sur une echelle 0-100.

    Ils sont volontairement hauts : le CDC2 section 2 rappelle que la bonne
    decision est souvent WAIT ou NO_TRADE. Rester des heures sans rien ouvrir
    est un fonctionnement normal, pas une panne.
    """

    strong: float = 85.0
    entry: float = 75.0
    wait: float = 55.0
    minimum_coverage: float = 0.60

    def __post_init__(self) -> None:
        if not self.strong >= self.entry >= self.wait >= 0:
            raise ValueError("Les seuils doivent être décroissants : strong >= entry >= wait >= 0.")
        if not 0.0 <= self.minimum_coverage <= 1.0:
            raise ValueError("La couverture minimale doit être comprise entre 0 et 1.")


@dataclass(slots=True)
class DecisionContext:
    """Tout ce sur quoi la decision s'appuie, et rien d'autre."""

    symbol: str
    analysis: AnalysisBundle
    source: DecisionSource = DecisionSource.AI_GENERATED
    now: datetime = field(default_factory=utcnow)

    proposed_direction: Direction | None = None
    levels: TradeLevels | None = None
    strategy: str | None = None

    # --- etat de l'intelligence ---
    consensus_required: bool = True

    # --- etat technique ---
    breaker: BreakerState | None = None
    mt5_connected: bool = True
    mt5_stable: bool = True

    # --- garde-fous d'exploitation ---
    trading_enabled: bool = True
    signal_complete: bool = True
    risk_computable: bool = True
    max_quote_age_seconds: float = 300.0
    thresholds: DecisionThresholds = field(default_factory=DecisionThresholds)

    # Seuil de confiance minimal exige, exprime sur 0-1 comme dans AISettings.
    min_confidence: float = 0.75

    @property
    def min_confidence_score(self) -> float:
        """Seuil exprime sur la meme echelle 0-100 que le score de confiance."""
        return max(0.0, min(1.0, self.min_confidence)) * 100.0

    @property
    def direction(self) -> Direction | None:
        """Direction envisagee : celle proposee, sinon celle des lectures."""
        if self.proposed_direction is not None:
            return self.proposed_direction
        return self.analysis.suggested_direction()


__all__ = ["DecisionContext", "DecisionThresholds"]
