"""Correlations mesurees entre instruments (CDC2 section 25).

Aucune correlation n'est ecrite en dur : tout est calcule sur les bougies
reellement disponibles. Deux series qui ne partagent pas assez d'horodatages
communs ne produisent pas une valeur approchee mais ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.services.historical_patterns.interface import as_utc
from app.services.mt5.interface import Candle

# En dessous de ce nombre d'observations communes, une correlation n'a pas de sens.
MIN_OBSERVATIONS = 20
STRONG_CORRELATION = 0.7


@dataclass(slots=True)
class CorrelationPair:
    """Correlation d'une paire d'instruments, recente et historique."""

    left: str
    right: str
    recent: float | None
    historical: float | None
    observations: int

    @property
    def drift(self) -> float | None:
        """Ecart entre le regime recent et le regime historique."""
        if self.recent is None or self.historical is None:
            return None
        return round(self.recent - self.historical, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left,
            "right": self.right,
            "recent": self.recent,
            "historical": self.historical,
            "drift": self.drift,
            "observations": self.observations,
        }


def returns_by_time(candles: Sequence[Candle]) -> dict[str, float]:
    """Rendements simples indexes par horodatage ISO."""
    ordered = sorted(candles, key=lambda candle: as_utc(candle.time))
    result: dict[str, float] = {}
    for index in range(1, len(ordered)):
        previous = ordered[index - 1].close
        if not previous:
            continue
        result[as_utc(ordered[index].time).isoformat()] = (ordered[index].close - previous) / previous
    return result


def aligned_returns(
    left: Sequence[Candle], right: Sequence[Candle], bars: int | None = None
) -> tuple[list[float], list[float]]:
    """Rendements des deux series sur leurs horodatages communs."""
    left_returns = returns_by_time(left)
    right_returns = returns_by_time(right)
    common = sorted(set(left_returns) & set(right_returns))
    if bars is not None and bars > 0:
        common = common[-bars:]
    return (
        [left_returns[moment] for moment in common],
        [right_returns[moment] for moment in common],
    )


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Coefficient de Pearson, ou None si indefini."""
    size = min(len(xs), len(ys))
    if size < MIN_OBSERVATIONS:
        return None
    mean_x = sum(xs[:size]) / size
    mean_y = sum(ys[:size]) / size
    covariance = 0.0
    variance_x = 0.0
    variance_y = 0.0
    for index in range(size):
        dx = xs[index] - mean_x
        dy = ys[index] - mean_y
        covariance += dx * dy
        variance_x += dx * dx
        variance_y += dy * dy
    if variance_x <= 0 or variance_y <= 0:
        return None
    return round(covariance / ((variance_x**0.5) * (variance_y**0.5)), 4)


def correlation(
    left: Sequence[Candle], right: Sequence[Candle], bars: int | None = None
) -> float | None:
    xs, ys = aligned_returns(left, right, bars)
    return pearson(xs, ys)


def correlation_matrix(
    series: Mapping[str, Sequence[Candle]], bars: int | None = None
) -> dict[str, dict[str, float]]:
    """Matrice symetrique des correlations mesurables.

    Les couples non mesurables sont simplement absents : aucune case n'est
    remplie par defaut.
    """
    symbols = sorted(series)
    matrix: dict[str, dict[str, float]] = {symbol: {} for symbol in symbols}
    for index, left in enumerate(symbols):
        for right in symbols[index + 1 :]:
            value = correlation(series[left], series[right], bars)
            if value is None:
                continue
            matrix[left][right] = value
            matrix[right][left] = value
    return matrix


def compare_windows(
    series: Mapping[str, Sequence[Candle]], recent_bars: int, historical_bars: int
) -> list[CorrelationPair]:
    """Correlations recentes et historiques pour chaque paire d'instruments."""
    symbols = sorted(series)
    pairs: list[CorrelationPair] = []
    for index, left in enumerate(symbols):
        for right in symbols[index + 1 :]:
            xs, ys = aligned_returns(series[left], series[right])
            pairs.append(
                CorrelationPair(
                    left=left,
                    right=right,
                    recent=correlation(series[left], series[right], recent_bars),
                    historical=correlation(series[left], series[right], historical_bars),
                    observations=min(len(xs), len(ys)),
                )
            )
    return pairs


__all__ = [
    "MIN_OBSERVATIONS",
    "STRONG_CORRELATION",
    "CorrelationPair",
    "aligned_returns",
    "compare_windows",
    "correlation",
    "correlation_matrix",
    "pearson",
    "returns_by_time",
]
