"""Score global sur 100, critere par critere (CDC3 sections 24 et 25).

Deux idees gouvernent ce module.

La premiere : aucun critere ne decide seul. Un RSI en survente ne vaut que ses
dix points sur cent, et un indicateur ne peut jamais declencher un signal a
lui tout seul (CDC3 section 10).

La seconde : un critere sans donnee n'est pas un critere neutre. Il est retire
du calcul et la couverture baisse. Un setup techniquement parfait mais sans
aucune actualite disponible plafonne donc mecaniquement — c'est exactement ce
que demande le CDC3 section 65 : degrader plutot qu'inventer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import Direction
from app.models.intelligence import TrendState
from app.services.technical_analysis.structure import (
    STRUCTURE_BEARISH,
    STRUCTURE_BULLISH,
)
from app.watcher.analysis.context import MarketContext
from app.watcher.config import WatcherConfig
from app.watcher.levels import TradeLevels
from app.watcher.models import VolatilityLevel

# Pente, en pourcentage de prix par barre, consideree comme franchement
# directionnelle. Au-dela, le critere momentum est sature.
STRONG_SLOPE = 0.12
# Distance, en ATR, au-dela de laquelle un objectif a toute la place voulue.
FULL_ROOM_ATR = 3.0
# Risk/Reward au-dela duquel le critere est sature.
FULL_RR = 3.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class CriterionScore:
    """Note d'un critere. ``available`` a faux retire le critere du calcul."""

    key: str
    label: str
    weight: float
    ratio: float | None = None
    available: bool = False
    detail: str = "Donnee indisponible."

    @property
    def points(self) -> float:
        if not self.available or self.ratio is None:
            return 0.0
        return self.weight * self.ratio

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "ratio": round(self.ratio, 3) if self.ratio is not None else None,
            "points": round(self.points, 2),
            "available": self.available,
            "detail": self.detail,
        }


@dataclass(slots=True)
class ScoreCard:
    """Resultat complet du calcul pour un sens donne."""

    direction: Direction
    criteria: list[CriterionScore] = field(default_factory=list)
    raw_score: float = 0.0
    coverage: float = 0.0
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> int:
        """Score de confiance sur 100. Ce n'est PAS une probabilite de gain."""
        return round(self.score)

    @property
    def missing(self) -> list[str]:
        return [item.label for item in self.criteria if not item.available]

    def grade(self) -> str:
        """Palier lisible (CDC3 section 24)."""
        if self.score >= 90:
            return "EXCEPTIONAL SETUP"
        if self.score >= 80:
            return "STRONG SIGNAL"
        if self.score >= 70:
            return "VALID SIGNAL"
        if self.score >= 60:
            return "WEAK SIGNAL"
        if self.score >= 50:
            return "WATCH"
        return "NO TRADE"

    def breakdown(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "score": round(self.score, 1),
            "rawScore": round(self.raw_score, 1),
            "coverage": round(self.coverage, 3),
            "grade": self.grade(),
            "criteria": [item.to_dict() for item in self.criteria],
            "missing": self.missing,
        }


def score_direction(
    context: MarketContext,
    direction: Direction,
    levels: TradeLevels | None,
    config: WatcherConfig,
) -> ScoreCard:
    """Note un sens donne sur 100, critere par critere."""
    card = ScoreCard(direction=direction)
    card.criteria = [
        _structure(context, direction, config),
        _multi_timeframe(context, direction, config),
        _momentum(context, direction, config),
        _support_resistance(context, direction, config),
        _volume(context, direction, config),
        _volatility(context, config),
        _indicators(context, direction, config),
        _sentiment(context, direction, config),
        _fundamental(context, direction, config),
        _risk_reward(levels, config),
    ]

    available_weight = sum(item.weight for item in card.criteria if item.available)
    points = sum(item.points for item in card.criteria)
    if available_weight > 0:
        card.raw_score = points / available_weight * 100.0
    card.coverage = available_weight / config.total_weight if config.total_weight else 0.0
    # Le score publie combine ce que disent les donnees et la quantite de
    # donnees disponibles. Sans actualites, un setup parfait plafonne.
    card.score = round(card.raw_score * card.coverage, 1)

    card.reasons = [
        f"{item.label} : {item.detail}"
        for item in card.criteria
        if item.available and item.ratio is not None and item.ratio >= 0.65
    ]
    card.risks = [
        f"{item.label} : {item.detail}"
        for item in card.criteria
        if item.available and item.ratio is not None and item.ratio <= 0.35
    ]
    card.risks.extend(
        f"{item.label} : donnee indisponible, confiance reduite."
        for item in card.criteria
        if not item.available
    )
    return card


# ---------------------------------------------------------------------------
# Criteres
# ---------------------------------------------------------------------------
def _structure(
    context: MarketContext, direction: Direction, config: WatcherConfig
) -> CriterionScore:
    """Structure de marche : HH/HL, LH/LL, BOS et CHoCH (CDC3 section 7)."""
    item = CriterionScore("market_structure", "Structure", config.weight("market_structure"))
    analysis = context.primary
    if analysis is None or not analysis.usable:
        return item

    buy = direction is Direction.BUY
    ratio = 0.5
    notes: list[str] = []
    label = analysis.structure.label
    favourable = STRUCTURE_BULLISH if buy else STRUCTURE_BEARISH
    contrary = STRUCTURE_BEARISH if buy else STRUCTURE_BULLISH

    if label == favourable:
        ratio += 0.35
        notes.append("sequence favorable")
    elif label == contrary:
        ratio -= 0.35
        notes.append("sequence contraire")
    else:
        notes.append(f"sequence {label.lower()}")

    event = analysis.break_event
    if event is not None:
        aligned = (event.direction == "UP") == buy
        if event.kind == "BOS":
            ratio += 0.15 if aligned else -0.15
            notes.append("BOS aligne" if aligned else "BOS oppose")
        else:
            ratio += 0.10 if aligned else -0.20
            notes.append("CHoCH aligne" if aligned else "CHoCH oppose")

    if context.liquidity.bias == ("BULLISH" if buy else "BEARISH"):
        ratio += 0.10
        notes.append("balayage de liquidite favorable")
    elif context.liquidity.bias not in ("NEUTRAL", ""):
        ratio -= 0.10
        notes.append("balayage de liquidite defavorable")

    item.ratio = _clamp(ratio)
    item.available = True
    item.detail = ", ".join(notes)
    return item


def _multi_timeframe(
    context: MarketContext, direction: Direction, config: WatcherConfig
) -> CriterionScore:
    """Accord entre unites de temps (CDC3 section 6)."""
    item = CriterionScore("multi_timeframe", "Multi-timeframe", config.weight("multi_timeframe"))
    view = context.view
    if view is None or not view.verdicts:
        return item

    wanted = TrendState.BULLISH if direction is Direction.BUY else TrendState.BEARISH
    opposite = TrendState.BEARISH if direction is Direction.BUY else TrendState.BULLISH
    alignment = _clamp(view.alignment)

    if view.bias is wanted:
        ratio = 0.5 + alignment / 2.0
        detail = f"biais {view.bias.value} aligne, cohesion {round(alignment * 100)} %"
    elif view.bias is opposite:
        ratio = 0.5 - alignment / 2.0
        detail = f"biais {view.bias.value} oppose, cohesion {round(alignment * 100)} %"
    else:
        ratio = 0.45
        detail = "aucun biais dominant entre les unites de temps"

    if view.conflicts:
        ratio -= 0.05 * len(view.conflicts)
        detail += f", {len(view.conflicts)} conflit(s)"

    item.ratio = _clamp(ratio)
    item.available = True
    item.detail = detail
    return item


def _momentum(
    context: MarketContext, direction: Direction, config: WatcherConfig
) -> CriterionScore:
    """Pente, momentum brut et comportement de la derniere bougie."""
    item = CriterionScore("momentum", "Momentum", config.weight("momentum"))
    analysis = context.primary
    if analysis is None or analysis.slope is None:
        return item

    sign = 1.0 if direction is Direction.BUY else -1.0
    normalised = _clamp(analysis.slope * sign / STRONG_SLOPE, -1.0, 1.0)
    ratio = 0.5 + normalised / 2.0

    action = context.price_action
    wanted = "BULLISH" if direction is Direction.BUY else "BEARISH"
    if action.bias == wanted:
        ratio += 0.15
    elif action.bias != "NEUTRAL":
        ratio -= 0.15
    if action.pressure == "ESSOUFFLEMENT":
        ratio -= 0.10

    item.ratio = _clamp(ratio)
    item.available = True
    item.detail = (
        f"pente {round(analysis.slope, 3)} %/barre, pression {action.pressure.lower()}"
    )
    return item


def _support_resistance(
    context: MarketContext, direction: Direction, config: WatcherConfig
) -> CriterionScore:
    """Place disponible devant le prix et appui derriere lui (CDC3 section 8)."""
    item = CriterionScore(
        "support_resistance", "Supports / resistances", config.weight("support_resistance")
    )
    analysis = context.primary
    if analysis is None or analysis.atr is None or analysis.atr <= 0 or analysis.last_close is None:
        return item

    atr = analysis.atr
    buy = direction is Direction.BUY
    ahead = analysis.distance_to_resistance() if buy else analysis.distance_to_support()
    behind = analysis.distance_to_support() if buy else analysis.distance_to_resistance()

    if ahead is None:
        # Aucun niveau devant : la place est entiere, mais rien ne balise le
        # parcours. On ne peut pas en faire un argument fort.
        room = 0.70
        room_detail = "aucun niveau identifie devant le prix"
    else:
        room = _clamp(abs(ahead) / (atr * FULL_ROOM_ATR))
        room_detail = f"{round(abs(ahead) / atr, 2)} ATR de place devant"

    if behind is None:
        support = 0.5
        support_detail = "aucun appui identifie derriere le prix"
    else:
        support = _clamp(1.0 - abs(behind) / (atr * 2.0))
        support_detail = f"appui a {round(abs(behind) / atr, 2)} ATR"

    item.ratio = _clamp(room * 0.6 + support * 0.4)
    item.available = True
    item.detail = f"{room_detail}, {support_detail}"
    return item


def _volume(
    context: MarketContext, direction: Direction, config: WatcherConfig
) -> CriterionScore:
    """Activite mesuree. Toujours annoncee pour ce qu'elle est (CDC3 section 12)."""
    item = CriterionScore("volume", "Volume", config.weight("volume"))
    reading = context.volume
    if reading.ratio is None:
        return item

    base = {"RISING": 0.85, "STABLE": 0.55, "FALLING": 0.30}.get(reading.trend, 0.5)
    if reading.supports_breakout is True:
        base += 0.15
    elif reading.supports_breakout is False:
        base -= 0.15

    nature = "volume reel" if reading.real else "tick volume"
    item.ratio = _clamp(base)
    item.available = True
    item.detail = f"{reading.detail} ({nature})"
    return item


def _volatility(context: MarketContext, config: WatcherConfig) -> CriterionScore:
    """Une volatilite extreme rend les niveaux peu fiables (CDC3 section 11)."""
    item = CriterionScore("volatility", "Volatilite", config.weight("volatility"))
    reading = context.volatility
    if not reading.known:
        return item

    ratio = {
        VolatilityLevel.NORMAL: 1.0,
        VolatilityLevel.LOW: 0.55,
        VolatilityLevel.HIGH: 0.50,
        VolatilityLevel.EXTREME: 0.0,
    }.get(reading.level, 0.5)
    if reading.expansion and reading.level is not VolatilityLevel.EXTREME:
        ratio -= 0.15

    item.ratio = _clamp(ratio)
    item.available = True
    item.detail = reading.detail
    return item


def _indicators(
    context: MarketContext, direction: Direction, config: WatcherConfig
) -> CriterionScore:
    """Indicateurs classiques : une part du score, jamais la decision."""
    item = CriterionScore("indicators", "Indicateurs", config.weight("indicators"))
    analysis = context.primary
    if analysis is None or analysis.rsi is None or analysis.ma_slow is None:
        return item

    buy = direction is Direction.BUY
    sign = 1.0 if buy else -1.0
    votes: list[float] = []
    notes: list[str] = []

    if analysis.last_close is not None:
        above = analysis.last_close > analysis.ma_slow
        votes.append(1.0 if above == buy else -1.0)
        notes.append("prix au-dessus de la MM lente" if above else "prix sous la MM lente")

    if analysis.ma_fast is not None:
        crossed = analysis.ma_fast > analysis.ma_slow
        votes.append(1.0 if crossed == buy else -1.0)
        notes.append("MM rapide au-dessus" if crossed else "MM rapide en dessous")

    rsi = analysis.rsi
    if rsi >= 55:
        votes.append(1.0 * sign)
    elif rsi <= 45:
        votes.append(-1.0 * sign)
    else:
        votes.append(0.0)
    notes.append(f"RSI {round(rsi, 1)}")

    average = sum(votes) / len(votes) if votes else 0.0
    ratio = 0.5 + average / 2.0

    # Acheter en plein surachat, ou vendre en pleine survente, reste possible
    # mais merite une decote : la place restante est reduite.
    if (buy and rsi >= 75) or (not buy and rsi <= 25):
        ratio *= 0.75
        notes.append("zone extreme, place reduite")

    item.ratio = _clamp(ratio)
    item.available = True
    item.detail = ", ".join(notes)
    return item


def _sentiment(
    context: MarketContext, direction: Direction, config: WatcherConfig
) -> CriterionScore:
    """Sentiment issu des actualites deja collectees (CDC3 section 18)."""
    item = CriterionScore("sentiment", "Sentiment", config.weight("sentiment"))
    reading = context.sentiment
    if not reading.available or reading.score is None:
        item.detail = reading.detail
        return item

    sign = 1.0 if direction is Direction.BUY else -1.0
    ratio = 0.5 + _clamp(reading.score * sign / 100.0, -1.0, 1.0) / 2.0
    item.ratio = _clamp(ratio)
    item.available = True
    item.detail = f"{reading.label} ({reading.score:+.0f} sur {reading.sample} depeche(s))"
    return item


def _fundamental(
    context: MarketContext, direction: Direction, config: WatcherConfig
) -> CriterionScore:
    """Lecture fondamentale, uniquement si des elements existent (section 14)."""
    item = CriterionScore("fundamental", "Fondamental", config.weight("fundamental"))
    reading = context.fundamental
    if not reading.available:
        item.detail = reading.detail
        return item

    wanted = "BULLISH" if direction is Direction.BUY else "BEARISH"
    if reading.direction == wanted:
        ratio = 0.85
    elif reading.direction == "NEUTRAL":
        ratio = 0.5
    else:
        ratio = 0.20

    item.ratio = ratio
    item.available = True
    item.detail = f"{reading.direction} ({reading.importance})"
    return item


def _risk_reward(levels: TradeLevels | None, config: WatcherConfig) -> CriterionScore:
    """Rapport risque / rendement reellement calcule (CDC3 section 29)."""
    item = CriterionScore("risk_reward", "Risk/Reward", config.weight("risk_reward"))
    if levels is None or not levels.risk_rewards:
        item.detail = "Niveaux non calculables : aucun Risk/Reward mesurable."
        return item

    first = levels.first_risk_reward or 0.0
    best = levels.best_risk_reward or 0.0
    reference = max(first, best / 2.0)
    item.ratio = _clamp((reference - 0.5) / (FULL_RR - 0.5))
    item.available = True
    item.detail = "  ".join(
        f"TP{index + 1} 1:{value}" for index, value in enumerate(levels.risk_rewards)
    )
    return item


__all__ = ["CriterionScore", "ScoreCard", "score_direction"]
