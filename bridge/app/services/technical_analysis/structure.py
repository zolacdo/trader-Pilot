"""Lecture deterministe de la structure de marche (CDC2 section 20).

Swing points, sequences HH/HL et LH/LL, break of structure, change of
character, ranges, breakouts, pullbacks et niveaux support / resistance.
Toutes les fonctions sont pures : memes bougies, meme resultat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.services.mt5.interface import Candle
from app.services.technical_analysis import indicators

# Etiquettes de structure.
STRUCTURE_BULLISH = "HH_HL"
STRUCTURE_BEARISH = "LH_LL"
STRUCTURE_EXPANSION = "EXPANSION"
STRUCTURE_CONTRACTION = "CONTRACTION"
STRUCTURE_UNDEFINED = "UNDEFINED"

# En dessous de ce ratio d'efficience, le marche fait du surplace.
RANGE_EFFICIENCY = 0.25


@dataclass(slots=True)
class SwingPoint:
    """Extremum local confirme de chaque cote par ``strength`` bougies."""

    index: int
    time: datetime
    price: float
    kind: str  # "HIGH" ou "LOW"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "time": self.time.isoformat(),
            "price": self.price,
            "kind": self.kind,
        }


def find_swings(candles: list[Candle], strength: int = 2) -> list[SwingPoint]:
    """Extremums locaux, du plus ancien au plus recent.

    Une bougie est un sommet si son plus haut domine strictement les
    ``strength`` bougies de gauche et domine ou egale celles de droite.
    """
    strength = max(1, int(strength))
    if len(candles) < strength * 2 + 1:
        return []
    swings: list[SwingPoint] = []
    for index in range(strength, len(candles) - strength):
        candle = candles[index]
        left = candles[index - strength : index]
        right = candles[index + 1 : index + 1 + strength]
        if all(candle.high > item.high for item in left) and all(
            candle.high >= item.high for item in right
        ):
            swings.append(SwingPoint(index, candle.time, candle.high, "HIGH"))
        elif all(candle.low < item.low for item in left) and all(
            candle.low <= item.low for item in right
        ):
            swings.append(SwingPoint(index, candle.time, candle.low, "LOW"))
    return swings


@dataclass(slots=True)
class StructureReading:
    """Sequence des sommets et des creux, et son etiquette globale."""

    label: str = STRUCTURE_UNDEFINED
    high_labels: list[str] = field(default_factory=list)
    low_labels: list[str] = field(default_factory=list)
    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None
    previous_high: SwingPoint | None = None
    previous_low: SwingPoint | None = None

    @property
    def bullish(self) -> bool:
        return self.label == STRUCTURE_BULLISH

    @property
    def bearish(self) -> bool:
        return self.label == STRUCTURE_BEARISH

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "highs": list(self.high_labels),
            "lows": list(self.low_labels),
            "lastHigh": self.last_high.to_dict() if self.last_high else None,
            "lastLow": self.last_low.to_dict() if self.last_low else None,
        }


def read_structure(swings: list[SwingPoint], depth: int = 4) -> StructureReading:
    """Compare les derniers sommets entre eux et les derniers creux entre eux."""
    highs = [swing for swing in swings if swing.kind == "HIGH"]
    lows = [swing for swing in swings if swing.kind == "LOW"]
    reading = StructureReading()
    reading.last_high = highs[-1] if highs else None
    reading.last_low = lows[-1] if lows else None
    reading.previous_high = highs[-2] if len(highs) >= 2 else None
    reading.previous_low = lows[-2] if len(lows) >= 2 else None

    depth = max(2, int(depth))
    for index in range(max(1, len(highs) - depth), len(highs)):
        reading.high_labels.append("HH" if highs[index].price > highs[index - 1].price else "LH")
    for index in range(max(1, len(lows) - depth), len(lows)):
        reading.low_labels.append("HL" if lows[index].price > lows[index - 1].price else "LL")

    last_high_label = reading.high_labels[-1] if reading.high_labels else None
    last_low_label = reading.low_labels[-1] if reading.low_labels else None
    if last_high_label == "HH" and last_low_label == "HL":
        reading.label = STRUCTURE_BULLISH
    elif last_high_label == "LH" and last_low_label == "LL":
        reading.label = STRUCTURE_BEARISH
    elif last_high_label == "HH" and last_low_label == "LL":
        reading.label = STRUCTURE_EXPANSION
    elif last_high_label == "LH" and last_low_label == "HL":
        reading.label = STRUCTURE_CONTRACTION
    return reading


@dataclass(slots=True)
class BreakEvent:
    """Cassure d'un swing confirme, par une cloture."""

    direction: str  # "UP" ou "DOWN"
    kind: str  # "BOS" (continuation) ou "CHOCH" (retournement)
    level: float
    index: int
    time: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "kind": self.kind,
            "level": self.level,
            "time": self.time.isoformat(),
        }


def detect_break(
    candles: list[Candle], swings: list[SwingPoint], structure: StructureReading
) -> BreakEvent | None:
    """Derniere cassure de structure, qualifiee BOS ou CHOCH.

    CHOCH : la cassure va a l'encontre de la structure en place. C'est le
    premier signe mesurable d'un changement de caractere.
    """
    if not candles:
        return None
    candidates: list[BreakEvent] = []
    for swing, direction in ((structure.last_high, "UP"), (structure.last_low, "DOWN")):
        if swing is None:
            continue
        for index in range(swing.index + 1, len(candles)):
            candle = candles[index]
            broken = candle.close > swing.price if direction == "UP" else candle.close < swing.price
            if broken:
                kind = "BOS"
                if (direction == "UP" and structure.bearish) or (direction == "DOWN" and structure.bullish):
                    kind = "CHOCH"
                candidates.append(BreakEvent(direction, kind, swing.price, index, candle.time))
                break
    if not candidates:
        return None
    return max(candidates, key=lambda event: event.index)


@dataclass(slots=True)
class LevelCluster:
    """Zone de prix touchee plusieurs fois par des swings."""

    price: float
    touches: int

    def to_dict(self) -> dict[str, Any]:
        return {"price": self.price, "touches": self.touches}


@dataclass(slots=True)
class Levels:
    """Support et resistance les plus proches du prix courant."""

    support: float | None = None
    resistance: float | None = None
    supports: list[LevelCluster] = field(default_factory=list)
    resistances: list[LevelCluster] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "support": self.support,
            "resistance": self.resistance,
            "supports": [cluster.to_dict() for cluster in self.supports],
            "resistances": [cluster.to_dict() for cluster in self.resistances],
        }


def _cluster(prices: list[float], tolerance: float) -> list[LevelCluster]:
    """Regroupe des prix voisins : un niveau touche trois fois pese plus."""
    clusters: list[LevelCluster] = []
    for price in sorted(prices):
        if clusters and abs(price - clusters[-1].price) <= tolerance:
            last = clusters[-1]
            total = last.price * last.touches + price
            last.touches += 1
            last.price = total / last.touches
        else:
            clusters.append(LevelCluster(price=price, touches=1))
    return clusters


def levels_around(
    swings: list[SwingPoint], price: float, tolerance: float | None = None, maximum: int = 3
) -> Levels:
    """Niveaux issus des swings, regroupes puis classes autour du prix."""
    if not swings or price <= 0:
        return Levels()
    span = tolerance if tolerance and tolerance > 0 else abs(price) * 0.001
    clusters = _cluster([swing.price for swing in swings], span)
    below = [cluster for cluster in clusters if cluster.price < price]
    above = [cluster for cluster in clusters if cluster.price > price]
    below.sort(key=lambda cluster: price - cluster.price)
    above.sort(key=lambda cluster: cluster.price - price)
    levels = Levels(supports=below[:maximum], resistances=above[:maximum])
    levels.support = levels.supports[0].price if levels.supports else None
    levels.resistance = levels.resistances[0].price if levels.resistances else None
    return levels


@dataclass(slots=True)
class RangeReading:
    """Bornes observees et jugement range / hors range."""

    is_range: bool = False
    high: float | None = None
    low: float | None = None
    width: float | None = None
    position: float | None = None  # 0 = sur le bas, 1 = sur le haut
    efficiency: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "isRange": self.is_range,
            "high": self.high,
            "low": self.low,
            "width": self.width,
            "position": self.position,
            "efficiency": self.efficiency,
        }


def read_range(candles: list[Candle], lookback: int = 40) -> RangeReading:
    """Bornes du range et ratio d'efficience sur la fenetre observee."""
    if len(candles) < 5:
        return RangeReading()
    window = candles[-max(5, int(lookback)) :]
    high = max(candle.high for candle in window)
    low = min(candle.low for candle in window)
    width = high - low
    efficiency = indicators.efficiency_ratio(
        indicators.closes(window), period=min(len(window) - 1, 20)
    )
    position = None
    if width > 0:
        position = (window[-1].close - low) / width
    return RangeReading(
        is_range=bool(efficiency is not None and efficiency <= RANGE_EFFICIENCY and width > 0),
        high=high,
        low=low,
        width=width if width > 0 else None,
        position=position,
        efficiency=efficiency,
    )


def detect_breakout(
    candles: list[Candle],
    atr_value: float | None,
    lookback: int = 40,
    confirm: int = 2,
    threshold: float = 0.15,
) -> str | None:
    """Sortie nette des bornes precedentes, marge minimale en fraction d'ATR.

    Les ``confirm`` dernieres bougies sont exclues du calcul des bornes : on
    compare le present a un passe qui ne se contient pas lui-meme.
    """
    confirm = max(1, int(confirm))
    lookback = max(10, int(lookback))
    if len(candles) < lookback + confirm or atr_value is None or atr_value <= 0:
        return None
    reference = candles[-(lookback + confirm) : -confirm]
    if not reference:
        return None
    high = max(candle.high for candle in reference)
    low = min(candle.low for candle in reference)
    margin = atr_value * max(0.0, threshold)
    recent = candles[-confirm:]
    if any(candle.close > high + margin for candle in recent):
        return "UP"
    if any(candle.close < low - margin for candle in recent):
        return "DOWN"
    return None


def detect_pullback(
    candles: list[Candle], structure: StructureReading, bullish: bool
) -> float | None:
    """Profondeur du repli en cours, entre 0 et 1, ou ``None``.

    Un repli est reconnu entre 15 % et 78,6 % de la derniere impulsion : en
    dessous le marche n'a pas recule, au-dessus l'impulsion est invalidee.
    """
    if not candles:
        return None
    high = structure.last_high
    low = structure.last_low
    if high is None or low is None:
        return None
    close = candles[-1].close
    if bullish:
        if low.index >= high.index:
            return None
        amplitude = high.price - low.price
        if amplitude <= 0 or close >= high.price:
            return None
        depth = (high.price - close) / amplitude
    else:
        if high.index >= low.index:
            return None
        amplitude = high.price - low.price
        if amplitude <= 0 or close <= low.price:
            return None
        depth = (close - low.price) / amplitude
    if 0.15 <= depth <= 0.786:
        return depth
    return None


__all__ = [
    "RANGE_EFFICIENCY",
    "STRUCTURE_BEARISH",
    "STRUCTURE_BULLISH",
    "STRUCTURE_CONTRACTION",
    "STRUCTURE_EXPANSION",
    "STRUCTURE_UNDEFINED",
    "BreakEvent",
    "LevelCluster",
    "Levels",
    "RangeReading",
    "StructureReading",
    "SwingPoint",
    "detect_break",
    "detect_breakout",
    "detect_pullback",
    "find_swings",
    "levels_around",
    "read_range",
    "read_structure",
]
