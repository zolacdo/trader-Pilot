"""Ponderation des composantes de confiance (CDC2 section 43).

Les poids ne sont jamais codes en dur dans le calcul : ils vivent ici, sont
serialisables et remplacables. Un poids modifie doit changer le score, et un
test doit pouvoir le prouver.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from enum import StrEnum


class ConfidenceComponent(StrEnum):
    """Composantes prises en compte dans le score global."""

    TECHNICAL = "TECHNICAL"
    HISTORICAL = "HISTORICAL"
    MARKET_REGIME = "MARKET_REGIME"
    MACRO = "MACRO"
    NEWS = "NEWS"
    CROSS_MARKET = "CROSS_MARKET"
    TELEGRAM = "TELEGRAM"
    AI_CONSENSUS = "AI_CONSENSUS"


# Libelles destines a l'utilisateur : francais accentue.
COMPONENT_LABELS: dict[ConfidenceComponent, str] = {
    ConfidenceComponent.TECHNICAL: "Analyse technique",
    ConfidenceComponent.HISTORICAL: "Analogues historiques",
    ConfidenceComponent.MARKET_REGIME: "Régime de marché",
    ConfidenceComponent.MACRO: "Contexte macroéconomique",
    ConfidenceComponent.NEWS: "Actualités",
    ConfidenceComponent.CROSS_MARKET: "Corrélations inter-marchés",
    ConfidenceComponent.TELEGRAM: "Signal Telegram",
    ConfidenceComponent.AI_CONSENSUS: "Consensus des IA",
}

# Correspondance nom de champ <-> composante, pour la serialisation.
_FIELD_BY_COMPONENT: dict[ConfidenceComponent, str] = {
    ConfidenceComponent.TECHNICAL: "technical",
    ConfidenceComponent.HISTORICAL: "historical",
    ConfidenceComponent.MARKET_REGIME: "market_regime",
    ConfidenceComponent.MACRO: "macro",
    ConfidenceComponent.NEWS: "news",
    ConfidenceComponent.CROSS_MARKET: "cross_market",
    ConfidenceComponent.TELEGRAM: "telegram",
    ConfidenceComponent.AI_CONSENSUS: "ai_consensus",
}

_COMPONENT_BY_FIELD: dict[str, ConfidenceComponent] = {
    field: component for component, field in _FIELD_BY_COMPONENT.items()
}


class InvalidWeights(ValueError):
    """Ponderation refusee : negative, vide ou inconnue."""


@dataclass(frozen=True, slots=True)
class ConfidenceWeights:
    """Repartition initiale proposee par le CDC2 (section 43).

    Les valeurs sont des parts relatives : elles n'ont pas besoin de sommer a
    1, le moteur renormalise sur les composantes reellement disponibles.
    """

    technical: float = 0.25
    historical: float = 0.15
    market_regime: float = 0.10
    macro: float = 0.15
    news: float = 0.10
    cross_market: float = 0.10
    telegram: float = 0.10
    ai_consensus: float = 0.05

    def __post_init__(self) -> None:
        for field_name, value in asdict(self).items():
            if not isinstance(value, (int, float)):
                raise InvalidWeights(f"Poids non numérique pour « {field_name} ».")
            if value < 0:
                raise InvalidWeights(f"Poids négatif interdit pour « {field_name} ».")
        if self.total() <= 0:
            raise InvalidWeights("La somme des poids doit être strictement positive.")

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    def total(self) -> float:
        return float(sum(asdict(self).values()))

    def weight_of(self, component: ConfidenceComponent) -> float:
        return float(getattr(self, _FIELD_BY_COMPONENT[component]))

    def as_mapping(self) -> dict[ConfidenceComponent, float]:
        return {component: self.weight_of(component) for component in ConfidenceComponent}

    def to_dict(self) -> dict[str, float]:
        """Vue serialisable, clefs = valeurs de l'enumeration."""
        return {component.value: self.weight_of(component) for component in ConfidenceComponent}

    def normalized(self) -> ConfidenceWeights:
        """Meme repartition ramenee a une somme de 1."""
        total = self.total()
        return ConfidenceWeights(
            **{field: value / total for field, value in asdict(self).items()}
        )

    # ------------------------------------------------------------------
    # Ecriture
    # ------------------------------------------------------------------
    def with_changes(self, **changes: float) -> ConfidenceWeights:
        """Copie modifiee. Les noms inconnus sont refuses explicitement."""
        unknown = set(changes) - set(_COMPONENT_BY_FIELD)
        if unknown:
            raise InvalidWeights(f"Composante inconnue : {', '.join(sorted(unknown))}.")
        return replace(self, **changes)

    @classmethod
    def from_mapping(cls, values: Mapping[str, float]) -> ConfidenceWeights:
        """Construit une ponderation depuis une configuration utilisateur.

        Accepte indifferemment les noms de champs (``market_regime``) et les
        valeurs de l'enumeration (``MARKET_REGIME``). Une composante absente
        garde son poids par defaut.
        """
        resolved: dict[str, float] = {}
        for raw_key, raw_value in values.items():
            key = str(raw_key).strip()
            field_name = key if key in _COMPONENT_BY_FIELD else None
            if field_name is None:
                field_name = _FIELD_BY_COMPONENT.get(_safe_component(key))
            if field_name is None:
                raise InvalidWeights(f"Composante inconnue : {raw_key}.")
            resolved[field_name] = float(raw_value)
        return cls(**resolved)


def _safe_component(key: str) -> ConfidenceComponent | None:
    try:
        return ConfidenceComponent(key.upper())
    except ValueError:
        return None


DEFAULT_WEIGHTS = ConfidenceWeights()

__all__ = [
    "COMPONENT_LABELS",
    "DEFAULT_WEIGHTS",
    "ConfidenceComponent",
    "ConfidenceWeights",
    "InvalidWeights",
]
