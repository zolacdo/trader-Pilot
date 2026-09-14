"""Lecture du volume, sans jamais mentir sur sa nature (CDC3 section 12).

MetaTrader 5 expose deux volumes : le volume reel, que seuls certains brokers
transmettent, et le tick volume, qui compte les changements de cotation. La
couche MT5 du Bridge ne rapatrie que le tick volume ; ce module le declare
donc comme tel et ne le presente jamais comme un volume reel.

Un tick volume reste informatif — il mesure l'activite — mais il ne dit rien
des quantites echangees. Toute conclusion en tient compte.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from app.services.mt5.interface import Candle
from app.watcher.models import VolumeKind

# Profondeur de comparaison et seuils de jugement.
LOOKBACK = 30
HIGH_RATIO = 1.50
LOW_RATIO = 0.60
MINIMUM_SAMPLE = 10


@dataclass(slots=True)
class VolumeReading:
    """Activite observee sur la derniere bougie, rapportee a l'habitude."""

    kind: VolumeKind = VolumeKind.UNKNOWN
    last: int | None = None
    reference: float | None = None
    ratio: float | None = None
    trend: str = "UNKNOWN"
    supports_breakout: bool | None = None
    detail: str = "Aucun volume exploitable sur cet instrument."

    @property
    def real(self) -> bool:
        """Vrai uniquement si le broker fournit un veritable volume echange."""
        return self.kind is VolumeKind.REAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "last": self.last,
            "reference": self.reference,
            "ratio": self.ratio,
            "trend": self.trend,
            "supportsBreakout": self.supports_breakout,
            "detail": self.detail,
        }


def read_volume(candles: list[Candle], breakout: str | None = None) -> VolumeReading:
    """Compare le volume de la derniere bougie a la mediane des precedentes.

    ``breakout`` vaut ``"UP"``, ``"DOWN"`` ou ``None`` : quand une cassure est
    detectee par ailleurs, on dit si le volume l'accompagne ou non.
    """
    reading = VolumeReading()
    if not candles:
        return reading

    values = [int(candle.tick_volume) for candle in candles if candle.tick_volume > 0]
    if len(values) < MINIMUM_SAMPLE:
        reading.detail = (
            f"Volume insuffisant pour conclure ({len(values)} bougie(s) cotee(s) sur "
            f"{len(candles)})."
        )
        return reading

    # La couche MT5 du Bridge ne transmet que le tick volume : on le dit.
    reading.kind = VolumeKind.TICK
    window = values[-LOOKBACK:]
    reading.last = window[-1]
    # La mediane des bougies precedentes, pas de la serie entiere : inclure la
    # bougie courante lisserait justement ce qu'on cherche a mesurer.
    reference = median(window[:-1]) if len(window) > 1 else None
    if not reference or reference <= 0:
        reading.detail = "Activite mesuree, mais sans reference historique exploitable."
        return reading

    ratio = reading.last / reference
    reading.reference = round(reference, 1)
    reading.ratio = round(ratio, 2)

    if ratio >= HIGH_RATIO:
        reading.trend = "RISING"
        reading.detail = f"Activite soutenue : {round(ratio * 100)} % du tick volume habituel."
    elif ratio <= LOW_RATIO:
        reading.trend = "FALLING"
        reading.detail = f"Activite faible : {round(ratio * 100)} % du tick volume habituel."
    else:
        reading.trend = "STABLE"
        reading.detail = f"Activite normale : {round(ratio * 100)} % du tick volume habituel."

    if breakout in ("UP", "DOWN"):
        reading.supports_breakout = ratio >= HIGH_RATIO
        if reading.supports_breakout:
            reading.detail += " La cassure est accompagnee par l'activite."
        else:
            reading.detail += " La cassure n'est pas accompagnee par l'activite."

    return reading


__all__ = ["VolumeReading", "read_volume"]
