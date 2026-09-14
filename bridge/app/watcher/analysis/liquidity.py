"""Zones de liquidite et balayages (CDC3 section 13).

Les notions de sweep et de stop hunt sont des lectures, pas des faits : on ne
voit jamais les ordres, seulement le prix qui depasse un niveau evident puis
revient. Ce module se contente donc de constater ce depassement-retour et le
dit ainsi. Rien n'est presente comme une certitude.

Les niveaux evidents sont les sommets et creux egaux : plusieurs swings au
meme prix concentrent mecaniquement des stops.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.mt5.interface import Candle
from app.services.technical_analysis.structure import SwingPoint

# Nombre minimal de swings au meme niveau pour parler de niveau egal.
MIN_TOUCHES = 2
# Tolerance de regroupement, en fraction d'ATR.
CLUSTER_ATR = 0.25
# Profondeur de recherche d'un balayage, en bougies.
SWEEP_WINDOW = 5
# Part de l'ATR au-dela de laquelle un depassement compte vraiment.
SWEEP_MIN_ATR = 0.10


@dataclass(slots=True)
class LiquidityZone:
    """Niveau touche plusieurs fois par des swings de meme nature."""

    price: float
    touches: int
    kind: str  # "HIGH" ou "LOW"

    def to_dict(self) -> dict[str, Any]:
        return {"price": self.price, "touches": self.touches, "kind": self.kind}


@dataclass(slots=True)
class LiquidityReading:
    """Zones reperees et depassements constates."""

    equal_highs: list[LiquidityZone] = field(default_factory=list)
    equal_lows: list[LiquidityZone] = field(default_factory=list)
    sweep: str | None = None  # "HIGH" : sommets balayes, "LOW" : creux balayes
    sweep_price: float | None = None
    false_breakout: str | None = None  # "UP" ou "DOWN"
    detail: str = "Aucune zone de liquidite evidente."

    @property
    def bias(self) -> str:
        """Lecture directionnelle du balayage, quand il y en a un.

        Un balayage des sommets suivi d'un retour sous le niveau se lit comme
        une pression vendeuse, et inversement. C'est une lecture, pas une
        prevision.
        """
        if self.sweep == "HIGH":
            return "BEARISH"
        if self.sweep == "LOW":
            return "BULLISH"
        return "NEUTRAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "equalHighs": [zone.to_dict() for zone in self.equal_highs],
            "equalLows": [zone.to_dict() for zone in self.equal_lows],
            "sweep": self.sweep,
            "sweepPrice": self.sweep_price,
            "falseBreakout": self.false_breakout,
            "bias": self.bias,
            "detail": self.detail,
        }


def _equal_levels(prices: list[float], tolerance: float, kind: str) -> list[LiquidityZone]:
    """Regroupe des prix voisins et ne garde que les groupes reellement repetes."""
    zones: list[LiquidityZone] = []
    for price in sorted(prices):
        if zones and abs(price - zones[-1].price) <= tolerance:
            zone = zones[-1]
            total = zone.price * zone.touches + price
            zone.touches += 1
            zone.price = total / zone.touches
        else:
            zones.append(LiquidityZone(price=price, touches=1, kind=kind))
    return [zone for zone in zones if zone.touches >= MIN_TOUCHES]


def read_liquidity(
    candles: list[Candle], swings: list[SwingPoint], atr: float | None
) -> LiquidityReading:
    """Repere les niveaux egaux puis verifie s'ils viennent d'etre depasses."""
    reading = LiquidityReading()
    if not candles or not swings or not atr or atr <= 0:
        return reading

    tolerance = atr * CLUSTER_ATR
    reading.equal_highs = _equal_levels(
        [swing.price for swing in swings if swing.kind == "HIGH"], tolerance, "HIGH"
    )
    reading.equal_lows = _equal_levels(
        [swing.price for swing in swings if swing.kind == "LOW"], tolerance, "LOW"
    )

    window = candles[-SWEEP_WINDOW:]
    margin = atr * SWEEP_MIN_ATR
    last_close = candles[-1].close

    # Balayage des sommets : une meche est allee chercher au-dessus du niveau,
    # mais le prix a cloture en dessous. Le niveau a ete pris, pas conquis.
    for zone in sorted(reading.equal_highs, key=lambda item: -item.touches):
        pierced = any(candle.high > zone.price + margin for candle in window)
        if pierced and last_close < zone.price:
            reading.sweep = "HIGH"
            reading.sweep_price = round(zone.price, 6)
            break

    if reading.sweep is None:
        for zone in sorted(reading.equal_lows, key=lambda item: -item.touches):
            pierced = any(candle.low < zone.price - margin for candle in window)
            if pierced and last_close > zone.price:
                reading.sweep = "LOW"
                reading.sweep_price = round(zone.price, 6)
                break

    reading.false_breakout = _false_breakout(candles, atr)
    reading.detail = _describe(reading)
    return reading


def _false_breakout(candles: list[Candle], atr: float) -> str | None:
    """Cloture au-dela des bornes recentes, puis reintegration (CDC3 section 7).

    On compare les dernieres bougies aux bornes de la periode qui les precede :
    utiliser les bornes de la periode complete inclurait la cassure elle-meme
    et rendrait la detection impossible.
    """
    if len(candles) < SWEEP_WINDOW * 4:
        return None
    reference = candles[: -SWEEP_WINDOW]
    high = max(candle.high for candle in reference)
    low = min(candle.low for candle in reference)
    recent = candles[-SWEEP_WINDOW:]
    margin = atr * SWEEP_MIN_ATR
    last_close = candles[-1].close

    if any(candle.close > high + margin for candle in recent[:-1]) and last_close < high:
        return "UP"
    if any(candle.close < low - margin for candle in recent[:-1]) and last_close > low:
        return "DOWN"
    return None


def _describe(reading: LiquidityReading) -> str:
    parts: list[str] = []
    if reading.equal_highs:
        parts.append(f"{len(reading.equal_highs)} zone(s) de sommets egaux")
    if reading.equal_lows:
        parts.append(f"{len(reading.equal_lows)} zone(s) de creux egaux")
    if reading.sweep == "HIGH":
        parts.append(f"sommets balayes vers {round(reading.sweep_price or 0.0, 5)} puis rendus")
    elif reading.sweep == "LOW":
        parts.append(f"creux balayes vers {round(reading.sweep_price or 0.0, 5)} puis rendus")
    if reading.false_breakout == "UP":
        parts.append("cassure haussiere non tenue")
    elif reading.false_breakout == "DOWN":
        parts.append("cassure baissiere non tenue")
    return " ; ".join(parts) if parts else "Aucune zone de liquidite evidente."


__all__ = ["LiquidityReading", "LiquidityZone", "read_liquidity"]
