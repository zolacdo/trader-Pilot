"""Comportement du prix bougie par bougie (CDC3 section 9).

Rien ici n'est une certitude : un engulfing n'annonce pas une hausse, il
constate qu'une bougie a efface la precedente. Chaque figure detectee est donc
rendue avec ce qu'elle est — une observation — et pese seulement une part du
score global (CDC3 section 10).

Toutes les mesures sont relatives a l'amplitude moyenne recente : comparer des
tailles de bougies en valeur absolue n'a aucun sens d'un instrument a l'autre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.mt5.interface import Candle

# Profondeur de reference pour l'amplitude moyenne.
LOOKBACK = 20
MINIMUM_CANDLES = 5

# Seuils de forme, exprimes en fraction de l'amplitude de la bougie.
DOJI_BODY = 0.10
MARUBOZU_BODY = 0.90
PIN_WICK = 0.60
PIN_BODY = 0.35
MOMENTUM_RANGE = 1.50
MOMENTUM_BODY = 0.60
COMPRESSION_RANGE = 0.70
COMPRESSION_WINDOW = 3


@dataclass(slots=True)
class CandleShape:
    """Geometrie d'une bougie, normalisee."""

    open: float
    high: float
    low: float
    close: float

    @property
    def amplitude(self) -> float:
        return max(0.0, self.high - self.low)

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return max(0.0, self.high - max(self.open, self.close))

    @property
    def lower_wick(self) -> float:
        return max(0.0, min(self.open, self.close) - self.low)

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_ratio(self) -> float:
        """Part du corps dans l'amplitude. Zero pour une bougie plate."""
        return self.body / self.amplitude if self.amplitude > 0 else 0.0

    @property
    def upper_ratio(self) -> float:
        return self.upper_wick / self.amplitude if self.amplitude > 0 else 0.0

    @property
    def lower_ratio(self) -> float:
        return self.lower_wick / self.amplitude if self.amplitude > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bodyRatio": round(self.body_ratio, 3),
            "upperWickRatio": round(self.upper_ratio, 3),
            "lowerWickRatio": round(self.lower_ratio, 3),
            "bullish": self.bullish,
        }


@dataclass(slots=True)
class PriceActionReading:
    """Figures observees sur la derniere bougie et pression qui s'en degage."""

    patterns: list[str] = field(default_factory=list)
    bias: str = "NEUTRAL"
    score: int = 0
    pressure: str = "UNKNOWN"
    relative_range: float | None = None
    shape: CandleShape | None = None
    compression: bool = False
    detail: str = "Historique trop court pour lire le comportement du prix."

    def to_dict(self) -> dict[str, Any]:
        return {
            "patterns": list(self.patterns),
            "bias": self.bias,
            "score": self.score,
            "pressure": self.pressure,
            "relativeRange": self.relative_range,
            "compression": self.compression,
            "shape": self.shape.to_dict() if self.shape else None,
            "detail": self.detail,
        }


def _shape(candle: Candle) -> CandleShape:
    return CandleShape(candle.open, candle.high, candle.low, candle.close)


def read_price_action(candles: list[Candle]) -> PriceActionReading:
    """Lit les dernieres bougies et en degage une pression acheteuse ou vendeuse."""
    reading = PriceActionReading()
    if len(candles) < MINIMUM_CANDLES:
        return reading

    window = candles[-LOOKBACK:]
    amplitudes = [max(0.0, candle.high - candle.low) for candle in window]
    average = sum(amplitudes) / len(amplitudes) if amplitudes else 0.0
    if average <= 0:
        reading.detail = "Bougies sans amplitude : instrument non cote sur cette periode."
        return reading

    last = _shape(candles[-1])
    previous = _shape(candles[-2])
    reading.shape = last
    reading.relative_range = round(last.amplitude / average, 2)

    patterns: list[str] = []
    score = 0

    # --- formes isolees ---
    if last.body_ratio <= DOJI_BODY:
        patterns.append("doji")
    if last.body_ratio >= MARUBOZU_BODY:
        patterns.append("marubozu haussier" if last.bullish else "marubozu baissier")
        score += 1 if last.bullish else -1

    if last.lower_ratio >= PIN_WICK and last.body_ratio <= PIN_BODY:
        patterns.append("pin bar haussier (rejet du bas)")
        score += 2
    elif last.upper_ratio >= PIN_WICK and last.body_ratio <= PIN_BODY:
        patterns.append("pin bar baissier (rejet du haut)")
        score -= 2

    # --- formes relatives a la bougie precedente ---
    if last.high < previous.high and last.low > previous.low:
        patterns.append("inside bar")
    elif last.high > previous.high and last.low < previous.low:
        patterns.append("outside bar")
        score += 1 if last.bullish else -1

    if last.bullish and previous.bearish and last.close > previous.open and last.open < previous.close:
        patterns.append("engulfing haussier")
        score += 2
    elif last.bearish and previous.bullish and last.close < previous.open and last.open > previous.close:
        patterns.append("engulfing baissier")
        score -= 2

    # --- dynamique ---
    if last.amplitude >= average * MOMENTUM_RANGE and last.body_ratio >= MOMENTUM_BODY:
        patterns.append("bougie de momentum")
        score += 1 if last.bullish else -1

    if len(amplitudes) > COMPRESSION_WINDOW:
        recent = amplitudes[-COMPRESSION_WINDOW:]
        if all(value <= average * COMPRESSION_RANGE for value in recent):
            reading.compression = True
            patterns.append("compression des amplitudes")

    reading.patterns = patterns
    reading.score = score
    if score >= 2:
        reading.bias = "BULLISH"
    elif score <= -2:
        reading.bias = "BEARISH"

    reading.pressure = _pressure(last, reading)
    reading.detail = ", ".join(patterns) if patterns else "Aucune figure marquante sur la derniere bougie."
    return reading


def _pressure(last: CandleShape, reading: PriceActionReading) -> str:
    """Traduit la forme de la bougie en pression lisible.

    L'essoufflement est le cas ou une grande bougie ne laisse presque pas de
    corps : le mouvement a ete tente puis rendu.
    """
    big = (reading.relative_range or 0.0) >= MOMENTUM_RANGE
    if big and last.body_ratio <= PIN_BODY:
        return "ESSOUFFLEMENT"
    if reading.compression:
        return "INDECISION"
    if reading.bias == "BULLISH":
        return "ACHETEUSE"
    if reading.bias == "BEARISH":
        return "VENDEUSE"
    if last.body_ratio <= DOJI_BODY:
        return "INDECISION"
    return "NEUTRE"


__all__ = ["CandleShape", "PriceActionReading", "read_price_action"]
