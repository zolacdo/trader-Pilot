"""Score de similarite entre deux situations de marche (CDC2 section 23).

Le score est explicite et verifiable : chaque caracteristique rapporte sa
propre contribution, et les caracteristiques absentes sont listees plutot que
remplacees par une valeur par defaut.

Un score eleve ne dit rien de la direction a prendre. Il dit seulement que
deux situations se ressemblent.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.historical_patterns.features import (
    CATEGORICAL_FEATURES,
    FEATURE_WEIGHTS,
    NUMERIC_FEATURES,
    FeatureVector,
)

# Avertissement systematiquement joint a toute sortie statistique.
SIMILARITY_WARNING = (
    "Ces analogues historiques sont une statistique descriptive, pas une prévision. "
    "Une proportion de cas positifs ne constitue jamais un ordre d'achat ou de vente : "
    "ce n'est qu'une composante parmi d'autres de la décision."
)

# Tolerance : au-dela de TOLERANCE_FACTOR ecarts-types, la similarite tombe a 0.
TOLERANCE_FACTOR = 2.0
MIN_SCALE = 1e-9


@dataclass(slots=True)
class SimilarityScore:
    """Resultat detaille d'une comparaison entre deux vecteurs."""

    value: float
    compared: int
    missing: list[str] = field(default_factory=list)
    per_feature: dict[str, float] = field(default_factory=dict)

    @property
    def percent(self) -> float:
        return round(self.value * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": round(self.value, 4),
            "percent": self.percent,
            "comparedFeatures": self.compared,
            "missingFeatures": list(self.missing),
            "perFeature": {name: round(score, 4) for name, score in self.per_feature.items()},
            "warning": SIMILARITY_WARNING,
        }


def feature_scales(vectors: Sequence[FeatureVector]) -> dict[str, float]:
    """Echelle de dispersion par caracteristique numerique.

    Calculee sur la population des candidats historiques uniquement : elle ne
    doit jamais dependre de donnees posterieures a l'analyse.
    """
    scales: dict[str, float] = {}
    for name in NUMERIC_FEATURES:
        values = [
            vector.numeric.get(name)
            for vector in vectors
            if vector.numeric.get(name) is not None
        ]
        clean = [value for value in values if value is not None]
        if len(clean) < 2:
            continue
        spread = statistics.pstdev(clean)
        if spread > MIN_SCALE:
            scales[name] = spread
    return scales


def similarity(
    reference: FeatureVector,
    candidate: FeatureVector,
    scales: Mapping[str, float] | None = None,
    weights: Mapping[str, float] | None = None,
    tolerance: float = TOLERANCE_FACTOR,
) -> SimilarityScore:
    """Similarite ponderee dans [0, 1] entre deux situations.

    Les caracteristiques numeriques sont comparees sur une distance normalisee
    par leur dispersion ; les caracteristiques categorielles par egalite.
    """
    used_scales = dict(scales or {})
    used_weights = dict(weights or FEATURE_WEIGHTS)

    per_feature: dict[str, float] = {}
    missing: list[str] = []
    total_weight = 0.0
    total_score = 0.0

    for name in NUMERIC_FEATURES:
        left = reference.numeric.get(name)
        right = candidate.numeric.get(name)
        if left is None or right is None:
            missing.append(name)
            continue
        scale = used_scales.get(name)
        if scale is None or scale <= MIN_SCALE:
            # Sans dispersion mesurable, on ne peut pas normaliser l'ecart :
            # la caracteristique est declaree non comparable plutot qu'inventee.
            missing.append(name)
            continue
        distance = abs(left - right) / (tolerance * scale)
        score = max(0.0, 1.0 - distance)
        weight = used_weights.get(name, 1.0)
        per_feature[name] = score
        total_score += score * weight
        total_weight += weight

    for name in CATEGORICAL_FEATURES:
        left = reference.categorical.get(name)
        right = candidate.categorical.get(name)
        if left is None or right is None:
            missing.append(name)
            continue
        score = 1.0 if left == right else 0.0
        weight = used_weights.get(name, 1.0)
        per_feature[name] = score
        total_score += score * weight
        total_weight += weight

    if total_weight <= 0:
        return SimilarityScore(value=0.0, compared=0, missing=missing)
    return SimilarityScore(
        value=max(0.0, min(1.0, total_score / total_weight)),
        compared=len(per_feature),
        missing=missing,
        per_feature=per_feature,
    )


__all__ = [
    "SIMILARITY_WARNING",
    "TOLERANCE_FACTOR",
    "SimilarityScore",
    "feature_scales",
    "similarity",
]
