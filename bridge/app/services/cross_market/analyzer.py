"""CrossMarketAnalyzer : relations mesurees entre instruments (CDC2 section 25).

L'analyseur ne connait aucune correlation a l'avance. Il charge les bougies
via la source injectee, mesure la correlation recente et la correlation
historique, et signale les couples dont la relation a change. Un couple non
mesurable n'apparait pas dans la matrice.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.cross_market.correlation import (
    STRONG_CORRELATION,
    CorrelationPair,
    compare_windows,
    correlation,
    correlation_matrix,
)
from app.services.cross_market.exposure import (
    DEFAULT_MAX_CORRELATED_EXPOSURE,
    DEFAULT_MAX_CURRENCY_EXPOSURE,
    ExposureAssessment,
    ExposureLeg,
    evaluate_correlated_exposure,
)
from app.services.historical_patterns.interface import (
    CandleProvider,
    MarketHistory,
    as_utc,
    timeframe_seconds,
)
from app.services.mt5.interface import Candle


def _now() -> datetime:
    return datetime.now(tz=UTC)


CROSS_MARKET_NOTE = (
    "Corrélations calculées sur les bougies réellement disponibles. "
    "Une corrélation est une observation passée : elle peut disparaître à tout moment."
)


@dataclass(slots=True)
class CrossMarketReport:
    """Photographie des relations entre les instruments observes."""

    computed_at: datetime
    timeframe: str
    recent_bars: int
    historical_bars: int
    symbols: list[str] = field(default_factory=list)
    pairs: list[CorrelationPair] = field(default_factory=list)
    recent_matrix: dict[str, dict[str, float]] = field(default_factory=dict)
    historical_matrix: dict[str, dict[str, float]] = field(default_factory=dict)
    unavailable: list[str] = field(default_factory=list)

    def strong_pairs(self, threshold: float = STRONG_CORRELATION) -> list[CorrelationPair]:
        return [
            pair
            for pair in self.pairs
            if pair.recent is not None and abs(pair.recent) >= threshold
        ]

    def regime_changes(self, minimum_drift: float = 0.4) -> list[CorrelationPair]:
        """Couples dont la relation recente s'ecarte nettement du passe."""
        return [
            pair
            for pair in self.pairs
            if pair.drift is not None and abs(pair.drift) >= minimum_drift
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "computedAt": self.computed_at.isoformat(),
            "timeframe": self.timeframe,
            "recentBars": self.recent_bars,
            "historicalBars": self.historical_bars,
            "symbols": list(self.symbols),
            "unavailable": list(self.unavailable),
            "pairs": [pair.to_dict() for pair in self.pairs],
            "strongPairs": [pair.to_dict() for pair in self.strong_pairs()],
            "regimeChanges": [pair.to_dict() for pair in self.regime_changes()],
            "recentMatrix": self.recent_matrix,
            "historicalMatrix": self.historical_matrix,
            "note": CROSS_MARKET_NOTE,
        }


class CrossMarketAnalyzer:
    """Calcule les correlations entre instruments et l'exposition agregee."""

    def __init__(
        self,
        provider: CandleProvider,
        timeframe: str = "H1",
        recent_bars: int = 120,
        historical_bars: int = 720,
    ) -> None:
        self.provider = provider
        self.timeframe = timeframe.upper()
        self.recent_bars = recent_bars
        self.historical_bars = historical_bars

    async def load(
        self, symbols: Sequence[str], end: datetime | None = None
    ) -> dict[str, list[Candle]]:
        """Charge les bougies de chaque instrument via la source injectee."""
        stop = as_utc(end) if end else _now()
        seconds = timeframe_seconds(self.timeframe) or 3600
        # Marge de securite : les week-ends et jours feries creusent des trous.
        span = timedelta(seconds=seconds * self.historical_bars * 2)
        series: dict[str, list[Candle]] = {}
        for symbol in symbols:
            candles = await self.provider.candles(symbol, self.timeframe, stop - span, stop)
            if candles:
                series[symbol] = list(candles)
        return series

    async def analyse(
        self, symbols: Sequence[str], end: datetime | None = None
    ) -> CrossMarketReport:
        series = await self.load(symbols, end)
        available = sorted(series)
        unavailable = sorted(set(symbols) - set(available))
        return CrossMarketReport(
            computed_at=as_utc(end) if end else _now(),
            timeframe=self.timeframe,
            recent_bars=self.recent_bars,
            historical_bars=self.historical_bars,
            symbols=available,
            pairs=compare_windows(series, self.recent_bars, self.historical_bars),
            recent_matrix=correlation_matrix(series, self.recent_bars),
            historical_matrix=correlation_matrix(series, self.historical_bars),
            unavailable=unavailable,
        )

    async def exposure(
        self,
        legs: Sequence[ExposureLeg],
        end: datetime | None = None,
        max_currency_exposure: float = DEFAULT_MAX_CURRENCY_EXPOSURE,
        max_correlated_exposure: float = DEFAULT_MAX_CORRELATED_EXPOSURE,
    ) -> tuple[ExposureAssessment, CrossMarketReport]:
        """Exposition agregee des positions, correlations calculees a la volee."""
        symbols = sorted({leg.symbol for leg in legs})
        report = await self.analyse(symbols, end)
        assessment = evaluate_correlated_exposure(
            legs,
            correlations=report.recent_matrix,
            max_currency_exposure=max_currency_exposure,
            max_correlated_exposure=max_correlated_exposure,
        )
        return assessment, report


def causal_correlation_feature(
    reference: MarketHistory,
    other: MarketHistory,
    timeframe: str = "H1",
    bars: int = 120,
) -> Callable[[datetime], float | None]:
    """Contexte cross-market utilisable comme caracteristique (CDC2 section 22).

    La fonction rendue calcule, pour un instant donne, la correlation entre
    deux instruments sur les seules bougies ANTERIEURES a cet instant. Elle
    peut donc etre passee a ``HistoricalPatternEngine.analyse`` sans
    reintroduire de look-ahead bias.
    """

    def compute(moment: datetime) -> float | None:
        left = reference.upto(timeframe, moment)[-(bars + 1) :]
        right = other.upto(timeframe, moment)[-(bars + 1) :]
        return correlation(left, right, bars)

    return compute


__all__ = [
    "CROSS_MARKET_NOTE",
    "CrossMarketAnalyzer",
    "CrossMarketReport",
    "causal_correlation_feature",
]
