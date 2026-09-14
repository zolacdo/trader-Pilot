"""Volatilite courante comparee a son propre historique (CDC3 section 11).

Un ATR de 120 points ne veut rien dire dans l'absolu : il est enorme sur
EURUSD et banal sur BTCUSD. La seule mesure exploitable est le rapport entre
la volatilite d'aujourd'hui et celle que l'instrument connait d'habitude.

Quand l'historique est trop court pour etablir cette reference, le niveau
reste UNKNOWN : aucune classification n'est devinee (CDC3 section 65).
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from app.services.mt5.interface import Candle
from app.services.technical_analysis import indicators
from app.watcher.models import VolatilityLevel

# Periode de l'ATR courant, et profondeur sur laquelle on cherche la reference.
ATR_PERIOD = 14
REFERENCE_LOOKBACK = 100

# Bornes du rapport ATR courant / ATR habituel.
LOW_RATIO = 0.60
HIGH_RATIO = 1.40
EXTREME_RATIO = 2.20

# Au-dela de ce rapport entre l'ATR des 3 dernieres bougies et l'ATR courant,
# on parle d'explosion de volatilite : le marche vient de changer de regime.
EXPANSION_RATIO = 1.80
EXPANSION_WINDOW = 3


@dataclass(slots=True)
class VolatilityReading:
    """Ce que l'on sait de la volatilite, et ce que l'on ne sait pas."""

    level: VolatilityLevel = VolatilityLevel.UNKNOWN
    atr: float | None = None
    atr_ratio: float | None = None
    reference_atr: float | None = None
    ratio_to_reference: float | None = None
    expansion: bool = False
    detail: str = "Historique insuffisant pour situer la volatilite."

    @property
    def extreme(self) -> bool:
        return self.level is VolatilityLevel.EXTREME

    @property
    def known(self) -> bool:
        return self.level is not VolatilityLevel.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "atr": self.atr,
            "atrRatio": self.atr_ratio,
            "referenceAtr": self.reference_atr,
            "ratioToReference": self.ratio_to_reference,
            "expansion": self.expansion,
            "detail": self.detail,
        }


def _rolling_atrs(ranges: list[float], period: int, lookback: int) -> list[float]:
    """Suite des ATR successifs sur la profondeur demandee."""
    values: list[float] = []
    start = max(period, len(ranges) - lookback)
    for end in range(start, len(ranges) + 1):
        window = ranges[end - period : end]
        if len(window) == period:
            values.append(sum(window) / period)
    return values


def read_volatility(
    candles: list[Candle], period: int = ATR_PERIOD, lookback: int = REFERENCE_LOOKBACK
) -> VolatilityReading:
    """Classe la volatilite d'un instrument par rapport a ses propres habitudes."""
    reading = VolatilityReading()
    current = indicators.atr(candles, period)
    if current is None or current <= 0:
        return reading
    reading.atr = current
    last_close = candles[-1].close if candles else None
    if last_close:
        reading.atr_ratio = current / abs(last_close) * 100.0

    ranges = indicators.true_ranges(candles)
    history = _rolling_atrs(ranges, period, lookback)
    # Il faut assez d'ATR successifs pour que la mediane signifie quelque
    # chose. En dessous, on garde UNKNOWN plutot que de classer au hasard.
    if len(history) < period:
        reading.detail = (
            f"Seulement {len(history)} mesure(s) d'ATR disponibles : "
            "pas de reference historique fiable."
        )
        return reading

    reference = median(history)
    if reference <= 0:
        return reading
    ratio = current / reference
    reading.reference_atr = reference
    reading.ratio_to_reference = round(ratio, 2)

    if ratio < LOW_RATIO:
        reading.level = VolatilityLevel.LOW
        reading.detail = f"Volatilite faible : {round(ratio * 100)} % de son niveau habituel."
    elif ratio < HIGH_RATIO:
        reading.level = VolatilityLevel.NORMAL
        reading.detail = f"Volatilite normale : {round(ratio * 100)} % de son niveau habituel."
    elif ratio < EXTREME_RATIO:
        reading.level = VolatilityLevel.HIGH
        reading.detail = f"Volatilite elevee : {round(ratio * 100)} % de son niveau habituel."
    else:
        reading.level = VolatilityLevel.EXTREME
        reading.detail = (
            f"Volatilite extreme : {round(ratio * 100)} % de son niveau habituel. "
            "Les niveaux techniques perdent de leur fiabilite."
        )

    if len(ranges) >= EXPANSION_WINDOW:
        recent = sum(ranges[-EXPANSION_WINDOW:]) / EXPANSION_WINDOW
        if recent > current * EXPANSION_RATIO:
            reading.expansion = True
            reading.detail += " Expansion soudaine sur les dernieres bougies."

    return reading


__all__ = ["VolatilityReading", "read_volatility"]
