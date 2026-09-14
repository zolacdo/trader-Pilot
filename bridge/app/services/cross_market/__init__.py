"""Moteur cross-market (CDC2 sections 25 et 26).

Correlations calculees entre instruments accessibles et detection de
l'exposition correlee agregee. Aucune relation n'est codee en dur.
"""

from __future__ import annotations

from app.services.cross_market.analyzer import (
    CROSS_MARKET_NOTE,
    CrossMarketAnalyzer,
    CrossMarketReport,
    causal_correlation_feature,
)
from app.services.cross_market.correlation import (
    MIN_OBSERVATIONS,
    STRONG_CORRELATION,
    CorrelationPair,
    correlation,
    correlation_matrix,
    pearson,
)
from app.services.cross_market.exposure import (
    CorrelatedCluster,
    CurrencyExposure,
    ExposureAssessment,
    ExposureLeg,
    aggregate_currency_exposure,
    evaluate_correlated_exposure,
    split_symbol,
)

__all__ = [
    "CROSS_MARKET_NOTE",
    "MIN_OBSERVATIONS",
    "STRONG_CORRELATION",
    "CorrelatedCluster",
    "CorrelationPair",
    "CrossMarketAnalyzer",
    "CrossMarketReport",
    "CurrencyExposure",
    "ExposureAssessment",
    "ExposureLeg",
    "aggregate_currency_exposure",
    "causal_correlation_feature",
    "correlation",
    "correlation_matrix",
    "evaluate_correlated_exposure",
    "pearson",
    "split_symbol",
]
