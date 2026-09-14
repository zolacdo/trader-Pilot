"""Resultat REEL d'une configuration passee (CDC2 section 22).

C'est le seul module autorise a regarder les bougies posterieures a l'instant
analyse, et uniquement pour mesurer ce qui s'est produit ENSUITE. Les
caracteristiques d'une situation ne passent jamais par ici.

Un resultat incomplet (horizon non encore couvert par l'historique) vaut
``None`` et n'entre dans aucune moyenne.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.enums import Direction
from app.services.historical_patterns.interface import MarketHistory, as_utc, horizon_end

POSITIVE = "POSITIVE"
NEGATIVE = "NEGATIVE"
NEUTRAL = "NEUTRAL"
UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class Outcome:
    """Ce qui s'est reellement passe apres une configuration, en pourcentage."""

    horizon_hours: float
    complete: bool
    bars: int = 0
    move_pct: float | None = None
    mae_pct: float | None = None
    mfe_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizonHours": self.horizon_hours,
            "complete": self.complete,
            "bars": self.bars,
            "movePct": round(self.move_pct, 4) if self.move_pct is not None else None,
            "maePct": round(self.mae_pct, 4) if self.mae_pct is not None else None,
            "mfePct": round(self.mfe_pct, 4) if self.mfe_pct is not None else None,
        }


def evaluate_outcome(
    history: MarketHistory,
    moment: datetime,
    hours: float,
    timeframe: str = "H1",
    direction: Direction | None = None,
    entry_price: float | None = None,
) -> Outcome:
    """Mouvement, MAE et MFE observes entre moment et moment + hours.

    ``direction`` oriente la mesure : pour un SELL, une baisse est favorable.
    Sans direction, la mesure est simplement orientee a la hausse.
    """
    start = as_utc(moment)
    end = horizon_end(start, hours)

    reference = entry_price
    if reference is None:
        past = history.upto(timeframe, start)
        reference = past[-1].close if past else None
    if not reference:
        return Outcome(horizon_hours=hours, complete=False)

    window = history.future(timeframe, start, until=end)
    if not window:
        return Outcome(horizon_hours=hours, complete=False)

    # L'horizon n'est reellement couvert que si la serie se poursuit au-dela.
    complete = bool(history.future(timeframe, end))
    sign = -1.0 if direction is Direction.SELL else 1.0

    move = (window[-1].close - reference) / reference * 100 * sign
    highest = max(candle.high for candle in window)
    lowest = min(candle.low for candle in window)
    up_pct = (highest - reference) / reference * 100
    down_pct = (lowest - reference) / reference * 100
    if sign > 0:
        mfe, mae = up_pct, down_pct
    else:
        mfe, mae = -down_pct, -up_pct

    return Outcome(
        horizon_hours=hours,
        complete=complete,
        bars=len(window),
        move_pct=move if complete else None,
        mae_pct=min(0.0, mae) if complete else None,
        mfe_pct=max(0.0, mfe) if complete else None,
    )


def classify(move_pct: float | None, neutral_band_pct: float | None) -> str:
    """Classe un mouvement en positif, negatif ou neutre.

    La bande neutre est exprimee en pourcentage et derive de la volatilite de
    la situation : sans volatilite mesurable, le resultat reste indetermine.
    """
    if move_pct is None or neutral_band_pct is None or neutral_band_pct <= 0:
        return UNKNOWN
    if move_pct > neutral_band_pct:
        return POSITIVE
    if move_pct < -neutral_band_pct:
        return NEGATIVE
    return NEUTRAL


__all__ = [
    "NEGATIVE",
    "NEUTRAL",
    "POSITIVE",
    "UNKNOWN",
    "Outcome",
    "classify",
    "evaluate_outcome",
]
