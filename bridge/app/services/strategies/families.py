"""Les quatre familles de strategies implementees (CDC2 section 45).

Chacune est deterministe : memes lectures, meme proposition. Aucune ne fixe de
prix — elles disent seulement « il y a un setup, dans ce sens, de cette
qualite ». Les niveaux sont calcules ensuite par le planificateur.
"""

from __future__ import annotations

from app.models.enums import Direction
from app.models.intelligence import MarketRegime, TrendState
from app.services.decision.inputs import AnalysisBundle, PriceStructure
from app.services.strategies.base import (
    StrategyFamily,
    StrategyProposal,
    TradingStrategy,
    technical_strength,
)


def _trend_direction(bundle: AnalysisBundle) -> Direction | None:
    """Direction portee par les unites de temps superieures."""
    technical = bundle.technical
    if technical is None:
        return None
    if technical.trend_d1 is TrendState.BULLISH and technical.trend_h4 is TrendState.BULLISH:
        return Direction.BUY
    if technical.trend_d1 is TrendState.BEARISH and technical.trend_h4 is TrendState.BEARISH:
        return Direction.SELL
    return None


class TrendFollowingStrategy(TradingStrategy):
    """Suivre une tendance deja etablie, alignee sur plusieurs unites de temps."""

    name = "trend_following"
    family = StrategyFamily.TREND_FOLLOWING
    regimes = frozenset({MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN})
    enabled = True

    def evaluate(
        self, bundle: AnalysisBundle, structure: PriceStructure
    ) -> StrategyProposal | None:
        direction = _trend_direction(bundle)
        if direction is None:
            return None

        regime = bundle.market_regime
        wanted = MarketRegime.TRENDING_UP if direction is Direction.BUY else MarketRegime.TRENDING_DOWN
        if regime is not wanted:
            # Tendance et regime se contredisent : aucun setup de suivi.
            return None

        technical = bundle.technical
        aligned = technical.aligned_trends(direction) if technical else 0
        opposed = technical.opposed_trends(direction) if technical else 0
        if opposed:
            return None

        reasons = [f"Alignement de {aligned} unités de temps dans le sens de la tendance."]
        negatives: list[str] = []
        if aligned < 3:
            negatives.append("L'unité de temps intermédiaire n'est pas encore alignée.")

        score = 0.5 * technical_strength(bundle) + 0.5 * (aligned / 3.0)
        return StrategyProposal(
            strategy=self.name,
            family=self.family,
            direction=direction,
            score=score,
            reasons=reasons,
            negative_factors=negatives,
        )


class BreakoutStrategy(TradingStrategy):
    """Prendre une cassure nette d'un niveau, avec volatilite suffisante."""

    name = "breakout"
    family = StrategyFamily.BREAKOUT
    regimes = frozenset({MarketRegime.BREAKOUT, MarketRegime.HIGH_VOLATILITY})
    enabled = True

    # Une cassure est retenue au-dela de cette fraction d'ATR au-dessus du niveau.
    min_break_atr = 0.15

    def evaluate(
        self, bundle: AnalysisBundle, structure: PriceStructure
    ) -> StrategyProposal | None:
        atr = structure.atr
        if atr is None or atr <= 0:
            return None
        price = structure.last_price
        margin = self.min_break_atr * atr

        broken_up = [level for level in structure.resistances if price - level >= margin]
        broken_down = [level for level in structure.supports if level - price >= margin]

        if broken_up and not broken_down:
            direction = Direction.BUY
            level = max(broken_up)
        elif broken_down and not broken_up:
            direction = Direction.SELL
            level = min(broken_down)
        else:
            # Cassure des deux cotes ou d'aucun : lecture ambigue, on passe.
            return None

        distance = abs(price - level) / atr
        reasons = [
            f"Cassure confirmée du niveau {level:g} de {distance:.2f} ATR.",
        ]
        negatives: list[str] = []
        if distance > 2.0:
            negatives.append("Le prix est déjà loin du niveau cassé : entrée tardive possible.")

        # Une cassure trop etiree perd de l'interet : le score plafonne puis baisse.
        extension = max(0.0, 1.0 - max(0.0, distance - 1.0) / 2.0)
        score = 0.5 * technical_strength(bundle) + 0.5 * extension
        return StrategyProposal(
            strategy=self.name,
            family=self.family,
            direction=direction,
            score=score,
            reasons=reasons,
            negative_factors=negatives,
        )


class PullbackStrategy(TradingStrategy):
    """Entrer sur un repli, dans le sens de la tendance de fond."""

    name = "pullback"
    family = StrategyFamily.PULLBACK
    regimes = frozenset({MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN})
    enabled = True

    # Distance maximale au niveau de repli, en ATR.
    max_distance_atr = 1.0

    def evaluate(
        self, bundle: AnalysisBundle, structure: PriceStructure
    ) -> StrategyProposal | None:
        direction = _trend_direction(bundle)
        technical = bundle.technical
        if direction is None or technical is None:
            return None

        # Un repli suppose que l'unite de temps courte contredit la tendance.
        short_trend = technical.trend_h1
        counter = TrendState.BEARISH if direction is Direction.BUY else TrendState.BULLISH
        if short_trend not in (counter, TrendState.NEUTRAL):
            return None

        atr = structure.atr
        if atr is None or atr <= 0:
            return None

        price = structure.last_price
        if direction is Direction.BUY:
            level = structure.nearest_support(price)
        else:
            level = structure.nearest_resistance(price)
        if level is None:
            return None

        distance = abs(price - level) / atr
        if distance > self.max_distance_atr:
            return None

        reasons = [
            "Tendance de fond intacte et repli en cours.",
            f"Prix à {distance:.2f} ATR du niveau {level:g}.",
        ]
        negatives: list[str] = []
        if short_trend is counter:
            negatives.append("L'unité de temps courte est encore contre la tendance de fond.")

        proximity = 1.0 - min(1.0, distance / self.max_distance_atr)
        score = 0.5 * technical_strength(bundle) + 0.5 * proximity
        return StrategyProposal(
            strategy=self.name,
            family=self.family,
            direction=direction,
            score=score,
            reasons=reasons,
            negative_factors=negatives,
        )


class MeanReversionStrategy(TradingStrategy):
    """Jouer le retour vers le milieu d'un range clairement borne."""

    name = "mean_reversion"
    family = StrategyFamily.MEAN_REVERSION
    regimes = frozenset({MarketRegime.RANGING, MarketRegime.LOW_VOLATILITY})
    enabled = True

    # Part de la largeur du range au-dela de laquelle le prix est « a l'extreme ».
    extreme_ratio = 0.25

    def evaluate(
        self, bundle: AnalysisBundle, structure: PriceStructure
    ) -> StrategyProposal | None:
        support = structure.nearest_support(structure.last_price)
        resistance = structure.nearest_resistance(structure.last_price)
        if support is None or resistance is None:
            return None

        width = resistance - support
        if width <= 0:
            return None

        price = structure.last_price
        position = (price - support) / width

        if position <= self.extreme_ratio:
            direction = Direction.BUY
            extremity = 1.0 - position / self.extreme_ratio
            reasons = [f"Prix au bas du range, à {position:.0%} de sa largeur."]
        elif position >= 1.0 - self.extreme_ratio:
            direction = Direction.SELL
            extremity = (position - (1.0 - self.extreme_ratio)) / self.extreme_ratio
            reasons = [f"Prix au haut du range, à {position:.0%} de sa largeur."]
        else:
            return None

        negatives: list[str] = []
        atr = structure.atr
        if atr is not None and atr > 0 and width < 2 * atr:
            negatives.append("Range étroit au regard de la volatilité : marge de manœuvre faible.")

        score = 0.4 * technical_strength(bundle) + 0.6 * max(0.0, min(1.0, extremity))
        return StrategyProposal(
            strategy=self.name,
            family=self.family,
            direction=direction,
            score=score,
            reasons=reasons,
            negative_factors=negatives,
        )


__all__ = [
    "BreakoutStrategy",
    "MeanReversionStrategy",
    "PullbackStrategy",
    "TrendFollowingStrategy",
]
