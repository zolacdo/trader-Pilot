"""Validation walk-forward du moteur historique (CDC2 section 24).

L'historique est coupe en deux : une periode d'apprentissage, ou le moteur a
le droit de chercher des analogues, et une periode de validation, qu'il ne
connait pas. Aucune information ne traverse la frontiere :

* les fenetres candidates sont bornees par ``candidate_end = train_end`` ;
* le resultat de chaque candidate se termine avant ``train_end`` ;
* le resultat de la periode de validation ne sert qu'a compter les reussites,
  jamais a choisir les analogues.

Le taux de reussite mesure la coherence du moteur, pas une rentabilite.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.models.enums import Direction
from app.services.historical_patterns.engine import HistoricalPatternEngine
from app.services.historical_patterns.features import build_features
from app.services.historical_patterns.interface import MarketHistory, as_utc
from app.services.historical_patterns.outcomes import (
    NEGATIVE,
    NEUTRAL,
    POSITIVE,
    UNKNOWN,
    classify,
    evaluate_outcome,
)
from app.services.historical_patterns.similarity import SIMILARITY_WARNING

# Seuils de lecture d'une proportion de cas positifs. Volontairement prudents :
# entre les deux, le moteur ne se prononce pas.
BULLISH_SHARE = 55.0
BEARISH_SHARE = 45.0

WALK_FORWARD_NOTE = (
    "Le taux de réussite walk-forward mesure la cohérence statistique du moteur "
    "sur une période qu'il n'a pas explorée. Ce n'est ni une performance, ni une promesse."
)


@dataclass(slots=True)
class WalkForwardSplit:
    """Frontiere entre apprentissage et validation."""

    timeframe: str
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    train_bars: int
    validation_bars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "trainStart": self.train_start.isoformat(),
            "trainEnd": self.train_end.isoformat(),
            "validationStart": self.validation_start.isoformat(),
            "validationEnd": self.validation_end.isoformat(),
            "trainBars": self.train_bars,
            "validationBars": self.validation_bars,
        }


@dataclass(slots=True)
class WalkForwardEvaluation:
    """Un point de validation : ce que le passe suggerait, ce qui est arrive."""

    moment: datetime
    matches: int
    similarity_mean: float | None
    expected: str
    positive_share: float | None
    realized: str
    realized_move_pct: float | None
    hit: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "moment": self.moment.isoformat(),
            "matches": self.matches,
            "similarityMean": self.similarity_mean,
            "expected": self.expected,
            "positiveShare": self.positive_share,
            "realized": self.realized,
            "realizedMovePct": (
                round(self.realized_move_pct, 4) if self.realized_move_pct is not None else None
            ),
            "hit": self.hit,
        }


@dataclass(slots=True)
class WalkForwardReport:
    split: WalkForwardSplit
    horizon_hours: float
    evaluations: list[WalkForwardEvaluation] = field(default_factory=list)

    @property
    def directional(self) -> list[WalkForwardEvaluation]:
        return [item for item in self.evaluations if item.hit is not None]

    @property
    def hit_rate(self) -> float | None:
        directional = self.directional
        if not directional:
            return None
        hits = sum(1 for item in directional if item.hit)
        return round(hits * 100 / len(directional), 1)

    def to_dict(self, include_points: int = 20) -> dict[str, Any]:
        similarities = [
            item.similarity_mean for item in self.evaluations if item.similarity_mean is not None
        ]
        return {
            "split": self.split.to_dict(),
            "horizonHours": self.horizon_hours,
            "evaluations": len(self.evaluations),
            "directionalEvaluations": len(self.directional),
            "hitRate": self.hit_rate,
            "meanSimilarity": round(statistics.fmean(similarities), 4) if similarities else None,
            "meanMatches": (
                round(statistics.fmean([item.matches for item in self.evaluations]), 2)
                if self.evaluations
                else None
            ),
            "points": [item.to_dict() for item in self.evaluations[:include_points]],
            "note": WALK_FORWARD_NOTE,
            "warning": SIMILARITY_WARNING,
        }


def split_history(
    history: MarketHistory, timeframe: str = "H1", train_ratio: float = 0.7
) -> WalkForwardSplit | None:
    """Coupe l'historique disponible en apprentissage puis validation."""
    if not 0.1 <= train_ratio <= 0.9:
        return None
    moments = history.moments(timeframe)
    if len(moments) < 20:
        return None
    cut = int(len(moments) * train_ratio)
    if cut <= 0 or cut >= len(moments):
        return None
    return WalkForwardSplit(
        timeframe=timeframe.upper(),
        train_start=moments[0],
        train_end=moments[cut - 1],
        validation_start=moments[cut],
        validation_end=moments[-1],
        train_bars=cut,
        validation_bars=len(moments) - cut,
    )


def _expected_label(positive_share: float | None, negative_share: float | None) -> str:
    if positive_share is None:
        return UNKNOWN
    if positive_share >= BULLISH_SHARE:
        return POSITIVE
    if negative_share is not None and negative_share >= BULLISH_SHARE:
        return NEGATIVE
    if positive_share <= BEARISH_SHARE and (negative_share or 0) > positive_share:
        return NEGATIVE
    return NEUTRAL


def run_walk_forward(
    engine: HistoricalPatternEngine,
    history: MarketHistory,
    split: WalkForwardSplit | None = None,
    horizon_hours: float | None = None,
    step_bars: int = 12,
    max_points: int = 40,
    direction: Direction | None = None,
) -> WalkForwardReport | None:
    """Rejoue la periode de validation sans jamais y chercher d'analogues."""
    timeframe = engine.base_timeframe
    active_split = split or split_history(history, timeframe)
    if active_split is None:
        return None

    hours = float(horizon_hours if horizon_hours is not None else engine.horizon_hours)
    report = WalkForwardReport(split=active_split, horizon_hours=hours)

    latest = active_split.validation_end - timedelta(hours=hours)
    moments = history.moments(timeframe, start=active_split.validation_start, end=latest)
    selected = moments[:: max(1, step_bars)][:max_points]

    for moment in selected:
        analysis = engine.analyse(
            history,
            moment,
            direction=direction,
            candidate_end=active_split.train_end,
        )
        if analysis is None:
            continue
        summary = analysis.horizon_summary(hours)
        expected = _expected_label(summary["positiveShare"], summary["negativeShare"])

        reference = build_features(history, moment, timeframe=timeframe)
        band = None
        if reference is not None and reference.atr_relative is not None:
            band = reference.atr_relative * 100 * engine.neutral_atr_fraction
        outcome = evaluate_outcome(
            history,
            moment,
            hours,
            timeframe=timeframe,
            direction=direction,
            entry_price=reference.reference_price if reference else None,
        )
        realized = classify(outcome.move_pct, band)
        hit: bool | None = None
        if expected in (POSITIVE, NEGATIVE) and realized in (POSITIVE, NEGATIVE, NEUTRAL):
            hit = expected == realized

        report.evaluations.append(
            WalkForwardEvaluation(
                moment=as_utc(moment),
                matches=analysis.matches,
                similarity_mean=analysis.similarity_mean,
                expected=expected,
                positive_share=summary["positiveShare"],
                realized=realized,
                realized_move_pct=outcome.move_pct,
                hit=hit,
            )
        )
    return report


__all__ = [
    "WALK_FORWARD_NOTE",
    "WalkForwardEvaluation",
    "WalkForwardReport",
    "WalkForwardSplit",
    "run_walk_forward",
    "split_history",
]
