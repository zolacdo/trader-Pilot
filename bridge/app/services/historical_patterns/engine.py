"""Moteur de recherche de configurations historiques comparables (CDC2 22-23).

Le principe est statistique, jamais conversationnel : on decrit la situation
courante par un vecteur de caracteristiques, on parcourt l'historique pour
trouver les fenetres qui lui ressemblent, puis on mesure ce qui s'est REELLEMENT
passe ensuite.

Deux regles structurent tout le module :

1. les caracteristiques d'une fenetre passee sont construites avec les seules
   bougies anterieures ou egales a cette fenetre (``MarketHistory.upto``) ;
2. une fenetre n'est retenue que si son horizon de resultat se termine AVANT
   l'instant analyse : sinon son resultat utiliserait des bougies que l'analyse
   n'est pas censee connaitre.

Le resultat n'est jamais une recommandation. Il est accompagne d'un
avertissement explicite.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.models.enums import Direction
from app.services.historical_patterns.features import (
    MIN_BARS,
    FeatureVector,
    build_features,
)
from app.services.historical_patterns.interface import MarketHistory, as_utc
from app.services.historical_patterns.outcomes import (
    NEGATIVE,
    NEUTRAL,
    POSITIVE,
    UNKNOWN,
    Outcome,
    classify,
    evaluate_outcome,
)
from app.services.historical_patterns.similarity import (
    SIMILARITY_WARNING,
    SimilarityScore,
    feature_scales,
    similarity,
)

DISCLAIMER = (
    "Statistiques historiques indicatives : elles ne prédisent aucune performance future."
)

DEFAULT_HORIZONS: tuple[float, ...] = (1.0, 4.0, 24.0)


@dataclass(slots=True)
class Analogue:
    """Une fenetre passee jugee comparable a la situation analysee."""

    moment: datetime
    score: SimilarityScore
    outcomes: dict[float, Outcome] = field(default_factory=dict)
    classification: str = UNKNOWN
    neutral_band_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "moment": self.moment.isoformat(),
            "similarity": round(self.score.value, 4),
            "similarityPercent": self.score.percent,
            "classification": self.classification,
            "neutralBandPct": (
                round(self.neutral_band_pct, 4) if self.neutral_band_pct is not None else None
            ),
            "outcomes": {
                f"{hours:g}h": outcome.to_dict() for hours, outcome in sorted(self.outcomes.items())
            },
        }


@dataclass(slots=True)
class PatternAnalysis:
    """Synthese statistique des configurations comparables trouvees."""

    symbol: str
    computed_at: datetime
    reference: FeatureVector
    horizon_hours: float
    analogues: list[Analogue] = field(default_factory=list)
    scanned: int = 0
    direction: Direction | None = None

    @property
    def matches(self) -> int:
        return len(self.analogues)

    @property
    def similarity_mean(self) -> float | None:
        if not self.analogues:
            return None
        return round(statistics.fmean(item.score.value for item in self.analogues), 4)

    def counts(self) -> dict[str, int]:
        buckets = {POSITIVE: 0, NEGATIVE: 0, NEUTRAL: 0, UNKNOWN: 0}
        for analogue in self.analogues:
            buckets[analogue.classification] = buckets.get(analogue.classification, 0) + 1
        return buckets

    def horizon_summary(self, hours: float) -> dict[str, Any]:
        """Statistiques pour un horizon donne, None si aucun echantillon complet."""
        moves: list[float] = []
        maes: list[float] = []
        mfes: list[float] = []
        positive = negative = neutral = 0
        for analogue in self.analogues:
            outcome = analogue.outcomes.get(hours)
            if outcome is None or not outcome.complete or outcome.move_pct is None:
                continue
            moves.append(outcome.move_pct)
            if outcome.mae_pct is not None:
                maes.append(outcome.mae_pct)
            if outcome.mfe_pct is not None:
                mfes.append(outcome.mfe_pct)
            label = classify(outcome.move_pct, analogue.neutral_band_pct)
            if label == POSITIVE:
                positive += 1
            elif label == NEGATIVE:
                negative += 1
            elif label == NEUTRAL:
                neutral += 1
        total = len(moves)
        return {
            "horizonHours": hours,
            "samples": total,
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "positiveShare": round(positive * 100 / total, 1) if total else None,
            "negativeShare": round(negative * 100 / total, 1) if total else None,
            "neutralShare": round(neutral * 100 / total, 1) if total else None,
            "averageMovePct": round(statistics.fmean(moves), 4) if moves else None,
            "medianMovePct": round(statistics.median(moves), 4) if moves else None,
            "averageMaePct": round(statistics.fmean(maes), 4) if maes else None,
            "averageMfePct": round(statistics.fmean(mfes), 4) if mfes else None,
        }

    def distribution(self, buckets: int = 5) -> dict[str, Any]:
        """Repartition des mouvements de l'horizon principal."""
        moves = [
            analogue.outcomes[self.horizon_hours].move_pct
            for analogue in self.analogues
            if self.horizon_hours in analogue.outcomes
            and analogue.outcomes[self.horizon_hours].move_pct is not None
        ]
        clean = [value for value in moves if value is not None]
        if not clean:
            return {"samples": 0, "buckets": []}
        low, high = min(clean), max(clean)
        if high <= low:
            return {"samples": len(clean), "buckets": [{"from": low, "to": high, "count": len(clean)}]}
        width = (high - low) / buckets
        rows: list[dict[str, Any]] = []
        for index in range(buckets):
            start = low + index * width
            end = high if index == buckets - 1 else start + width
            count = sum(1 for value in clean if start <= value <= end) if index == buckets - 1 else (
                sum(1 for value in clean if start <= value < end)
            )
            rows.append(
                {
                    "from": round(start, 4),
                    "to": round(end, 4),
                    "count": count,
                    "share": round(count * 100 / len(clean), 1),
                }
            )
        return {"samples": len(clean), "buckets": rows}

    def to_dict(self, include_analogues: int = 10) -> dict[str, Any]:
        counts = self.counts()
        return {
            "symbol": self.symbol,
            "computedAt": self.computed_at.isoformat(),
            "direction": self.direction.value if self.direction else None,
            "horizonHours": self.horizon_hours,
            "scannedWindows": self.scanned,
            "matches": self.matches,
            "similarityMean": self.similarity_mean,
            "similarityMeanPercent": (
                round(self.similarity_mean * 100, 1) if self.similarity_mean is not None else None
            ),
            "positive": counts.get(POSITIVE, 0),
            "negative": counts.get(NEGATIVE, 0),
            "neutral": counts.get(NEUTRAL, 0),
            "undetermined": counts.get(UNKNOWN, 0),
            "referenceFeatures": self.reference.to_dict(),
            "horizons": [self.horizon_summary(hours) for hours in self._horizons()],
            "distribution": self.distribution(),
            "analogues": [item.to_dict() for item in self.analogues[:include_analogues]],
            "warning": SIMILARITY_WARNING,
            "disclaimer": DISCLAIMER,
        }

    def _horizons(self) -> list[float]:
        seen: list[float] = []
        for analogue in self.analogues:
            for hours in analogue.outcomes:
                if hours not in seen:
                    seen.append(hours)
        return sorted(seen)


class HistoricalPatternEngine:
    """Recherche statistique de situations comparables dans le passe."""

    def __init__(
        self,
        base_timeframe: str = "H1",
        horizons: Sequence[float] = DEFAULT_HORIZONS,
        horizon_hours: float = 4.0,
        min_similarity: float = 0.7,
        max_matches: int = 200,
        max_candidates: int = 4000,
        step_bars: int = 1,
        neutral_atr_fraction: float = 0.25,
    ) -> None:
        self.base_timeframe = base_timeframe.upper()
        self.horizons = tuple(sorted({float(value) for value in horizons} | {float(horizon_hours)}))
        self.horizon_hours = float(horizon_hours)
        self.min_similarity = min_similarity
        self.max_matches = max_matches
        self.max_candidates = max_candidates
        self.step_bars = max(1, step_bars)
        self.neutral_atr_fraction = neutral_atr_fraction

    # -- selection des fenetres candidates --------------------------------

    def candidate_moments(
        self,
        history: MarketHistory,
        as_of: datetime,
        candidate_end: datetime | None = None,
    ) -> list[datetime]:
        """Instants passes exploitables, resultat complet inclus.

        Une fenetre n'est candidate que si son horizon le plus long se termine
        avant la borne de connaissance : c'est la barriere anti look-ahead.
        """
        reference = as_utc(as_of)
        limit = min(reference, as_utc(candidate_end)) if candidate_end else reference
        longest = timedelta(hours=max(self.horizons))
        latest = limit - longest
        moments = history.moments(self.base_timeframe, end=latest)
        if len(moments) <= MIN_BARS:
            return []
        # Les premieres bougies servent de rodage aux indicateurs.
        usable = moments[MIN_BARS:]
        selected = usable[:: self.step_bars]
        if len(selected) > self.max_candidates:
            selected = selected[-self.max_candidates :]
        return selected

    # -- analyse ----------------------------------------------------------

    def analyse(
        self,
        history: MarketHistory,
        as_of: datetime,
        direction: Direction | None = None,
        candidate_end: datetime | None = None,
        spread_points: int | None = None,
        point: float | None = None,
        cross_market_at: Callable[[datetime], float | None] | None = None,
    ) -> PatternAnalysis | None:
        """Analyse la situation a ``as_of`` et rend la synthese statistique.

        ``cross_market_at`` fournit le contexte inter-instruments d'un instant.
        Il est applique a la situation courante ET a chaque fenetre candidate,
        et doit lui-meme etre causal (voir ``causal_correlation_feature``).

        Retourne None si la situation courante ne peut pas etre decrite
        (historique trop court) : rien n'est extrapole.
        """
        reference = build_features(
            history,
            as_of,
            timeframe=self.base_timeframe,
            spread_points=spread_points,
            point=point,
            cross_market=cross_market_at(as_of) if cross_market_at else None,
        )
        if reference is None:
            return None

        moments = self.candidate_moments(history, as_of, candidate_end)
        vectors: list[FeatureVector] = []
        for moment in moments:
            vector = build_features(
                history,
                moment,
                timeframe=self.base_timeframe,
                cross_market=cross_market_at(moment) if cross_market_at else None,
            )
            if vector is not None:
                vectors.append(vector)

        analysis = PatternAnalysis(
            symbol=history.symbol,
            computed_at=as_utc(as_of),
            reference=reference,
            horizon_hours=self.horizon_hours,
            scanned=len(vectors),
            direction=direction,
        )
        if not vectors:
            return analysis

        scales = feature_scales(vectors)
        matches: list[Analogue] = []
        for vector in vectors:
            score = similarity(reference, vector, scales)
            if score.compared == 0 or score.value < self.min_similarity:
                continue
            matches.append(self._build_analogue(history, vector, score, direction))

        matches.sort(key=lambda item: item.score.value, reverse=True)
        analysis.analogues = matches[: self.max_matches]
        return analysis

    def _build_analogue(
        self,
        history: MarketHistory,
        vector: FeatureVector,
        score: SimilarityScore,
        direction: Direction | None,
    ) -> Analogue:
        band = None
        if vector.atr_relative is not None:
            band = vector.atr_relative * 100 * self.neutral_atr_fraction
        outcomes = {
            hours: evaluate_outcome(
                history,
                vector.moment,
                hours,
                timeframe=self.base_timeframe,
                direction=direction,
                entry_price=vector.reference_price,
            )
            for hours in self.horizons
        }
        main = outcomes.get(self.horizon_hours)
        classification = classify(main.move_pct if main else None, band)
        return Analogue(
            moment=vector.moment,
            score=score,
            outcomes=outcomes,
            classification=classification,
            neutral_band_pct=band,
        )


__all__ = [
    "DEFAULT_HORIZONS",
    "DISCLAIMER",
    "Analogue",
    "HistoricalPatternEngine",
    "PatternAnalysis",
]
