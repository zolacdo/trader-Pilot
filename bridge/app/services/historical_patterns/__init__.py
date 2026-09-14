"""Moteur de patterns historiques (CDC2 sections 22 a 24).

Analyse statistique de l'historique : recherche de fenetres comparables,
score de similarite explicite, mesure des resultats reels et validation
walk-forward. Aucune sortie de ce module ne constitue une recommandation.
"""

from __future__ import annotations

from app.services.historical_patterns.engine import (
    DISCLAIMER,
    Analogue,
    HistoricalPatternEngine,
    PatternAnalysis,
)
from app.services.historical_patterns.features import (
    FEATURE_WEIGHTS,
    FeatureVector,
    build_features,
)
from app.services.historical_patterns.interface import (
    CandleProvider,
    LookAheadError,
    MarketHistory,
    StaticCandleProvider,
    load_history,
)
from app.services.historical_patterns.outcomes import Outcome, classify, evaluate_outcome
from app.services.historical_patterns.similarity import (
    SIMILARITY_WARNING,
    SimilarityScore,
    feature_scales,
    similarity,
)
from app.services.historical_patterns.walk_forward import (
    WalkForwardReport,
    WalkForwardSplit,
    run_walk_forward,
    split_history,
)

__all__ = [
    "DISCLAIMER",
    "FEATURE_WEIGHTS",
    "SIMILARITY_WARNING",
    "Analogue",
    "CandleProvider",
    "FeatureVector",
    "HistoricalPatternEngine",
    "LookAheadError",
    "MarketHistory",
    "Outcome",
    "PatternAnalysis",
    "SimilarityScore",
    "StaticCandleProvider",
    "WalkForwardReport",
    "WalkForwardSplit",
    "build_features",
    "classify",
    "evaluate_outcome",
    "feature_scales",
    "load_history",
    "run_walk_forward",
    "similarity",
    "split_history",
]
