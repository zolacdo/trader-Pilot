"""Caracteristiques decrivant une situation de marche (CDC2 section 22).

Chaque valeur est calculee UNIQUEMENT a partir des bougies dont l'horodatage
est anterieur ou egal a l'instant analyse. Le vecteur est construit depuis
``MarketHistory.upto`` : aucune fonction de ce module n'appelle ``future()``.

Une caracteristique qui ne peut pas etre mesuree vaut ``None`` : jamais zero,
jamais une valeur inventee.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.intelligence import MarketRegime, TrendState
from app.services.historical_patterns.interface import MarketHistory, as_utc
from app.services.mt5.interface import Candle

# Poids relatifs utilises par le score de similarite. Modifiables par appel.
FEATURE_WEIGHTS: dict[str, float] = {
    "trend_d1": 1.2,
    "trend_h4": 1.2,
    "trend_h1": 1.0,
    "atr_relative": 1.0,
    "momentum": 1.0,
    "distance_support": 0.8,
    "distance_resistance": 0.8,
    "rsi": 1.0,
    "volatility": 0.8,
    "spread_relative": 0.4,
    "cross_market": 0.8,
    "regime": 1.5,
    "session": 0.8,
    "structure": 1.0,
}

NUMERIC_FEATURES: tuple[str, ...] = (
    "trend_d1",
    "trend_h4",
    "trend_h1",
    "atr_relative",
    "momentum",
    "distance_support",
    "distance_resistance",
    "rsi",
    "volatility",
    "spread_relative",
    "cross_market",
)

CATEGORICAL_FEATURES: tuple[str, ...] = ("regime", "session", "structure")

# Nombre minimal de bougies pour que les indicateurs aient un sens.
MIN_BARS = 60
ATR_PERIOD = 14
RSI_PERIOD = 14
MOMENTUM_BARS = 10
LEVEL_BARS = 50
STRUCTURE_BARS = 40
VOLATILITY_BARS = 20


@dataclass(slots=True)
class FeatureVector:
    """Photographie normalisee d'une situation a un instant donne."""

    moment: datetime
    numeric: dict[str, float | None]
    categorical: dict[str, str | None]
    reference_price: float | None = None
    atr: float | None = None
    atr_relative: float | None = None

    def value(self, name: str) -> Any:
        if name in self.numeric:
            return self.numeric[name]
        return self.categorical.get(name)

    def available(self) -> list[str]:
        return [
            name
            for name in (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES)
            if self.value(name) is not None
        ]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"moment": self.moment.isoformat()}
        payload.update(
            {
                name: (round(value, 6) if isinstance(value, float) else value)
                for name, value in self.numeric.items()
            }
        )
        payload.update(self.categorical)
        payload["referencePrice"] = self.reference_price
        payload["atr"] = round(self.atr, 6) if self.atr is not None else None
        return payload


# ---------------------------------------------------------------------------
# Indicateurs elementaires
# ---------------------------------------------------------------------------

def ema(values: Sequence[float], period: int) -> float | None:
    """Moyenne mobile exponentielle, ou None si la serie est trop courte."""
    if period <= 0 or len(values) < period:
        return None
    seed = sum(values[:period]) / period
    factor = 2.0 / (period + 1)
    result = seed
    for value in values[period:]:
        result = value * factor + result * (1 - factor)
    return result


def true_ranges(candles: Sequence[Candle]) -> list[float]:
    ranges: list[float] = []
    for index in range(1, len(candles)):
        current, previous = candles[index], candles[index - 1]
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return ranges


def atr(candles: Sequence[Candle], period: int = ATR_PERIOD) -> float | None:
    """Average True Range simple, ou None si la serie est trop courte.

    Seule la queue utile de la serie est parcourue : l'analyse balaie des
    milliers de fenetres, chaque indicateur doit rester a cout constant.
    """
    if period <= 0 or len(candles) < period + 1:
        return None
    ranges = true_ranges(candles[-(period + 1):])
    if len(ranges) < period:
        return None
    return sum(ranges[-period:]) / period


def rsi(closes: Sequence[float], period: int = RSI_PERIOD) -> float | None:
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, len(closes)):
        delta = closes[index] - closes[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    average_gain = sum(gains[-period:]) / period
    average_loss = sum(losses[-period:]) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    strength = average_gain / average_loss
    return 100.0 - (100.0 / (1 + strength))


def trend_score(candles: Sequence[Candle]) -> float | None:
    """Force de tendance dans [-1, 1] : ecart EMA20/EMA50 rapporte a l'ATR."""
    if len(candles) < 51:
        return None
    window = candles[-90:]
    closes = [candle.close for candle in window]
    fast = ema(closes[-60:], 20)
    slow = ema(closes[-80:], 50)
    reference = atr(window, ATR_PERIOD)
    if fast is None or slow is None or not reference:
        return None
    raw = (fast - slow) / reference
    return max(-1.0, min(1.0, raw / 3.0))


def trend_state(score: float | None, threshold: float = 0.15) -> TrendState:
    if score is None:
        return TrendState.NEUTRAL
    if score >= threshold:
        return TrendState.BULLISH
    if score <= -threshold:
        return TrendState.BEARISH
    return TrendState.NEUTRAL


def session_of(moment: datetime) -> str:
    """Session de marche deduite de l'heure UTC."""
    hour = as_utc(moment).hour
    if 0 <= hour < 7:
        return "ASIA"
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 17:
        return "LONDON_NEWYORK"
    if 17 <= hour < 21:
        return "NEWYORK"
    return "OFF_HOURS"


def structure_of(candles: Sequence[Candle], bars: int = STRUCTURE_BARS) -> str | None:
    """Structure de marche : sommets et creux montants, descendants ou melanges."""
    if len(candles) < bars:
        return None
    window = candles[-bars:]
    half = bars // 2
    first = window[:half]
    second = window[half:]
    high_first = max(candle.high for candle in first)
    high_second = max(candle.high for candle in second)
    low_first = min(candle.low for candle in first)
    low_second = min(candle.low for candle in second)
    if high_second > high_first and low_second > low_first:
        return "HIGHER_HIGH_HIGHER_LOW"
    if high_second < high_first and low_second < low_first:
        return "LOWER_HIGH_LOWER_LOW"
    return "RANGE"


def regime_of(candles: Sequence[Candle], trend: float | None) -> str:
    """Regime observe, deduit de la volatilite relative et de la tendance."""
    short = atr(candles, ATR_PERIOD)
    long_period = min(50, max(ATR_PERIOD, len(candles) - 2))
    long_term = atr(candles, long_period)
    if short is None or not long_term:
        return MarketRegime.UNCERTAIN.value
    ratio = short / long_term
    if ratio >= 1.4:
        return MarketRegime.HIGH_VOLATILITY.value
    if ratio <= 0.6:
        return MarketRegime.LOW_VOLATILITY.value
    if trend is None:
        return MarketRegime.UNCERTAIN.value
    if trend >= 0.3:
        return MarketRegime.TRENDING_UP.value
    if trend <= -0.3:
        return MarketRegime.TRENDING_DOWN.value
    return MarketRegime.RANGING.value


def _volatility(candles: Sequence[Candle], bars: int = VOLATILITY_BARS) -> float | None:
    if len(candles) < bars + 1:
        return None
    closes = [candle.close for candle in candles[-(bars + 1):]]
    returns = [
        (closes[index] - closes[index - 1]) / closes[index - 1]
        for index in range(1, len(closes))
        if closes[index - 1]
    ]
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns)


# ---------------------------------------------------------------------------
# Construction du vecteur
# ---------------------------------------------------------------------------

def build_features(
    history: MarketHistory,
    moment: datetime,
    timeframe: str = "H1",
    spread_points: int | None = None,
    point: float | None = None,
    cross_market: float | None = None,
) -> FeatureVector | None:
    """Vecteur de caracteristiques a un instant, sans aucune bougie future.

    ``cross_market`` est le contexte inter-instruments (CDC2 section 22) :
    il est injecte par l'appelant, qui reste responsable de le calculer sur le
    seul passe. Non fourni, il vaut None et n'entre pas dans la comparaison.

    Retourne None si l'historique disponible avant ``moment`` est trop court.
    """
    base = history.upto(timeframe, moment)
    if len(base) < MIN_BARS:
        return None

    # Les indicateurs ne regardent qu'une queue bornee : le cout d'une fenetre
    # ne doit pas dependre de la longueur totale de l'historique.
    recent = base[-120:]
    closes = [candle.close for candle in recent]
    last_close = closes[-1]
    reference_atr = atr(recent, ATR_PERIOD)
    atr_relative = (reference_atr / last_close) if reference_atr and last_close else None

    trend_h1 = trend_score(recent)
    trend_h4 = trend_score(history.upto("H4", moment)) if history.has("H4") else None
    trend_d1 = trend_score(history.upto("D1", moment)) if history.has("D1") else None

    momentum = None
    if len(closes) > MOMENTUM_BARS and closes[-(MOMENTUM_BARS + 1)]:
        past = closes[-(MOMENTUM_BARS + 1)]
        momentum = (last_close - past) / past

    distance_support = None
    distance_resistance = None
    if reference_atr and len(recent) >= LEVEL_BARS:
        window = recent[-LEVEL_BARS:]
        support = min(candle.low for candle in window)
        resistance = max(candle.high for candle in window)
        distance_support = (last_close - support) / reference_atr
        distance_resistance = (resistance - last_close) / reference_atr

    raw_rsi = rsi(closes[-(RSI_PERIOD + 1):], RSI_PERIOD)
    spread_relative = None
    if spread_points is not None and point is not None and last_close:
        spread_relative = (spread_points * point) / last_close

    numeric: dict[str, float | None] = {
        "trend_d1": trend_d1,
        "trend_h4": trend_h4,
        "trend_h1": trend_h1,
        "atr_relative": atr_relative,
        "momentum": momentum,
        "distance_support": distance_support,
        "distance_resistance": distance_resistance,
        "rsi": (raw_rsi / 100.0) if raw_rsi is not None else None,
        "volatility": _volatility(recent),
        "spread_relative": spread_relative,
        "cross_market": cross_market,
    }
    categorical: dict[str, str | None] = {
        "regime": regime_of(recent, trend_h1),
        "session": session_of(as_utc(recent[-1].time)),
        "structure": structure_of(recent),
    }
    return FeatureVector(
        moment=as_utc(moment),
        numeric=numeric,
        categorical=categorical,
        reference_price=last_close,
        atr=reference_atr,
        atr_relative=atr_relative,
    )


__all__ = [
    "CATEGORICAL_FEATURES",
    "FEATURE_WEIGHTS",
    "MIN_BARS",
    "NUMERIC_FEATURES",
    "FeatureVector",
    "atr",
    "build_features",
    "ema",
    "regime_of",
    "rsi",
    "session_of",
    "structure_of",
    "trend_score",
    "trend_state",
]
