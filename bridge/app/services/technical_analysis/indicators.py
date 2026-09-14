"""Indicateurs deterministes calcules sur des bougies reelles (CDC2 section 20).

Volontairement peu nombreux : ATR, RSI, moyennes mobiles, momentum, volatilite
et pente. Chaque fonction est pure, testable, et rend ``None`` des que
l'historique est insuffisant. Aucune valeur n'est extrapolee ni approchee.
"""

from __future__ import annotations

from app.services.mt5.interface import Candle


def closes(candles: list[Candle]) -> list[float]:
    return [candle.close for candle in candles]


def true_range(previous_close: float, candle: Candle) -> float:
    """Amplitude vraie d'une bougie, gaps compris."""
    return max(
        candle.high - candle.low,
        abs(candle.high - previous_close),
        abs(candle.low - previous_close),
    )


def true_ranges(candles: list[Candle]) -> list[float]:
    """Amplitudes vraies successives. La premiere bougie n'en a pas."""
    if len(candles) < 2:
        return []
    return [true_range(candles[index - 1].close, candles[index]) for index in range(1, len(candles))]


def atr(candles: list[Candle], period: int = 14) -> float | None:
    """Average True Range : moyenne simple des ``period`` dernieres amplitudes.

    La moyenne simple est retenue plutot que le lissage de Wilder : elle donne
    exactement le meme ordre de grandeur et reste verifiable a la main.
    """
    period = max(1, int(period))
    ranges = true_ranges(candles)
    if len(ranges) < period:
        return None
    window = ranges[-period:]
    return sum(window) / period


def rsi(values: list[float], period: int = 14) -> float | None:
    """RSI de Wilder sur une serie de cloture, entre 0 et 100."""
    period = max(2, int(period))
    if len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for index in range(1, period + 1):
        delta = values[index] - values[index - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    average_gain = gains / period
    average_loss = losses / period
    for index in range(period + 1, len(values)):
        delta = values[index] - values[index - 1]
        average_gain = (average_gain * (period - 1) + max(delta, 0.0)) / period
        average_loss = (average_loss * (period - 1) + max(-delta, 0.0)) / period
    if average_loss == 0.0:
        return 100.0 if average_gain > 0.0 else 50.0
    strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + strength))


def sma(values: list[float], period: int) -> float | None:
    """Moyenne mobile simple sur les ``period`` dernieres valeurs."""
    period = max(1, int(period))
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values: list[float], period: int) -> float | None:
    """Moyenne mobile exponentielle, amorcee par la moyenne simple."""
    period = max(1, int(period))
    if len(values) < period:
        return None
    factor = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = value * factor + current * (1.0 - factor)
    return current


def momentum(values: list[float], period: int = 10) -> float | None:
    """Variation en pourcentage sur ``period`` barres."""
    period = max(1, int(period))
    if len(values) < period + 1:
        return None
    reference = values[-(period + 1)]
    if reference == 0.0:
        return None
    return (values[-1] - reference) / abs(reference) * 100.0


def simple_returns(values: list[float]) -> list[float]:
    """Rendements simples successifs, en pourcentage."""
    result: list[float] = []
    for index in range(1, len(values)):
        previous = values[index - 1]
        if previous == 0.0:
            continue
        result.append((values[index] - previous) / abs(previous) * 100.0)
    return result


def stdev(values: list[float]) -> float | None:
    """Ecart-type d'echantillon. ``None`` en dessous de deux valeurs."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return variance**0.5


def volatility(values: list[float], period: int = 20) -> float | None:
    """Ecart-type des rendements recents, en pourcentage par barre."""
    period = max(2, int(period))
    series = simple_returns(values)
    if len(series) < period:
        return None
    return stdev(series[-period:])


def efficiency_ratio(values: list[float], period: int = 20) -> float | None:
    """Ratio d'efficience de Kaufman : trajet net / trajet parcouru.

    Proche de 1 quand le marche avance en ligne droite, proche de 0 quand il
    fait du surplace. C'est la mesure utilisee pour distinguer une tendance
    d'un range, sans seuil subjectif sur le prix.
    """
    period = max(2, int(period))
    if len(values) < period + 1:
        return None
    window = values[-(period + 1) :]
    path = sum(abs(window[index] - window[index - 1]) for index in range(1, len(window)))
    if path == 0.0:
        return None
    return abs(window[-1] - window[0]) / path


def slope(values: list[float]) -> float | None:
    """Pente de la regression lineaire, en unites de prix par barre."""
    count = len(values)
    if count < 2:
        return None
    mean_x = (count - 1) / 2.0
    mean_y = sum(values) / count
    numerator = 0.0
    denominator = 0.0
    for index, value in enumerate(values):
        deviation = index - mean_x
        numerator += deviation * (value - mean_y)
        denominator += deviation * deviation
    if denominator == 0.0:
        return None
    return numerator / denominator


def normalised_slope(values: list[float], period: int | None = None) -> float | None:
    """Pente exprimee en pourcentage du prix moyen, par barre.

    Rend une grandeur comparable entre l'or a 3350 et l'EURUSD a 1.08.
    """
    series = values if period is None else values[-max(2, int(period)) :]
    raw = slope(series)
    if raw is None:
        return None
    mean = sum(series) / len(series)
    if mean == 0.0:
        return None
    return raw / abs(mean) * 100.0


__all__ = [
    "atr",
    "closes",
    "efficiency_ratio",
    "ema",
    "momentum",
    "normalised_slope",
    "rsi",
    "simple_returns",
    "slope",
    "sma",
    "stdev",
    "true_range",
    "true_ranges",
    "volatility",
]
