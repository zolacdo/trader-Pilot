"""Contrats d'entree du moteur de decision (CDC2 sections 36 et 42).

Ce fichier est la frontiere entre l'intelligence de decision et les modules
qui l'alimentent : donnees de marche, analyse technique, regime, analogues
historiques, macro, actualites, correlations, Telegram.

Aucun de ces modules n'est importe ici. Ils produisent ces structures, la
decision les consomme. Toutes les valeurs sont optionnelles : une donnee
absente reste ``None`` et se voit comptee comme absente, jamais comme neutre
inventee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.enums import Direction
from app.models.intelligence import MarketRegime, NewsImpact, TrendState
from app.services.confidence.engine import ComponentScore, aligned_score
from app.services.confidence.weights import ConfidenceComponent

# ---------------------------------------------------------------------------
# Prix et structure (produits par market_data/ et technical_analysis/)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class QuoteView:
    """Derniere cotation connue d'un instrument."""

    symbol: str
    bid: float | None = None
    ask: float | None = None
    spread_points: int | None = None
    captured_at: datetime | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    def age_seconds(self, now: datetime) -> float | None:
        if self.captured_at is None:
            return None
        return max(0.0, (now - self.captured_at).total_seconds())

    @property
    def consistent(self) -> bool:
        """Une cotation incoherente est un motif de refus (CDC2 section 113)."""
        if self.bid is None or self.ask is None:
            return False
        if self.bid <= 0 or self.ask <= 0:
            return False
        return self.ask >= self.bid


@dataclass(slots=True)
class PriceStructure:
    """Niveaux mesures sur le graphique, jamais proposes par une IA.

    ``supports`` et ``resistances`` sont des prix reels releves par le module
    d'analyse technique. ``atr`` porte la volatilite. Sans ATR ni structure,
    aucun niveau n'est calculable et le systeme refuse de trader.
    """

    symbol: str
    last_price: float
    atr: float | None = None
    digits: int = 5
    point: float | None = None
    supports: list[float] = field(default_factory=list)
    resistances: list[float] = field(default_factory=list)
    swing_high: float | None = None
    swing_low: float | None = None
    spread_points: int | None = None
    computed_at: datetime | None = None

    def supports_below(self, price: float) -> list[float]:
        return sorted((level for level in self.supports if level < price), reverse=True)

    def resistances_above(self, price: float) -> list[float]:
        return sorted(level for level in self.resistances if level > price)

    def nearest_support(self, price: float) -> float | None:
        below = self.supports_below(price)
        return below[0] if below else None

    def nearest_resistance(self, price: float) -> float | None:
        above = self.resistances_above(price)
        return above[0] if above else None

    @property
    def usable(self) -> bool:
        return self.last_price > 0 and self.atr is not None and self.atr > 0


@dataclass(slots=True)
class TradeLevels:
    """Plan de trade deterministe : entree, stop, cibles (CDC2 section 41)."""

    direction: Direction
    entry_price: float
    entry_min: float
    entry_max: float
    stop_loss: float
    take_profits: list[float] = field(default_factory=list)
    expected_rr: float | None = None
    first_target_rr: float | None = None
    risk_distance: float | None = None
    method: str = ""

    @property
    def valid(self) -> bool:
        """Un stop du mauvais cote ou colle a l'entree invalide le plan."""
        if self.risk_distance is None or self.risk_distance <= 0:
            return False
        if self.direction is Direction.BUY and self.stop_loss >= self.entry_price:
            return False
        if self.direction is Direction.SELL and self.stop_loss <= self.entry_price:
            return False
        return bool(self.take_profits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "entryPrice": self.entry_price,
            "entryMin": self.entry_min,
            "entryMax": self.entry_max,
            "stopLoss": self.stop_loss,
            "takeProfits": list(self.take_profits),
            "expectedRr": self.expected_rr,
            "firstTargetRr": self.first_target_rr,
            "riskDistance": self.risk_distance,
            "method": self.method,
        }


# ---------------------------------------------------------------------------
# Vues analytiques (une par module amont)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TechnicalView:
    """Sortie attendue de ``technical_analysis/`` (CDC2 section 20)."""

    score: float | None = None
    direction: Direction | None = None
    trend_d1: TrendState | None = None
    trend_h4: TrendState | None = None
    trend_h1: TrendState | None = None
    detail: str | None = None
    computed_at: datetime | None = None

    def aligned_trends(self, direction: Direction) -> int:
        """Nombre d'unites de temps qui vont dans le sens envisage."""
        wanted = TrendState.BULLISH if direction is Direction.BUY else TrendState.BEARISH
        return sum(1 for trend in (self.trend_d1, self.trend_h4, self.trend_h1) if trend is wanted)

    def opposed_trends(self, direction: Direction) -> int:
        opposite = TrendState.BEARISH if direction is Direction.BUY else TrendState.BULLISH
        return sum(1 for trend in (self.trend_d1, self.trend_h4, self.trend_h1) if trend is opposite)


@dataclass(slots=True)
class RegimeView:
    """Sortie attendue de ``market_regime/`` (CDC2 section 21)."""

    regime: MarketRegime | None = None
    score: float | None = None
    detail: str | None = None


@dataclass(slots=True)
class HistoricalView:
    """Sortie attendue de ``historical_patterns/`` (CDC2 section 22)."""

    score: float | None = None
    direction: Direction | None = None
    matches: int | None = None
    similarity: float | None = None
    detail: str | None = None


@dataclass(slots=True)
class MacroView:
    """Lecture macroeconomique (CDC2 section 28)."""

    score: float | None = None
    direction: Direction | None = None
    detail: str | None = None


@dataclass(slots=True)
class NewsView:
    """Sortie attendue de ``news/`` (CDC2 sections 27, 35 et 62)."""

    score: float | None = None
    blackout: bool = False
    minutes_to_event: int | None = None
    impact: NewsImpact | None = None
    analysable: bool = True
    detail: str | None = None


@dataclass(slots=True)
class CrossMarketView:
    """Sortie attendue de ``cross_market/`` (CDC2 section 25)."""

    score: float | None = None
    direction: Direction | None = None
    detail: str | None = None


@dataclass(slots=True)
class TelegramView:
    """Signal Telegram normalise (CDC2 sections 36 a 38)."""

    score: float | None = None
    direction: Direction | None = None
    complete: bool = True
    signal_id: int | None = None
    detail: str | None = None


@dataclass(slots=True)
class ConsensusView:
    """Resume du consensus IA, deja produit par ``ai_service.consensus``."""

    score: float | None = None
    direction: Direction | None = None
    available: bool = False
    blocks_auto_trade: bool = False
    needs_manual_review: bool = False
    detail: str | None = None


@dataclass(slots=True)
class AnalysisBundle:
    """Ensemble des lectures disponibles pour un instrument a un instant."""

    symbol: str
    quote: QuoteView | None = None
    technical: TechnicalView | None = None
    regime: RegimeView | None = None
    historical: HistoricalView | None = None
    macro: MacroView | None = None
    news: NewsView | None = None
    cross_market: CrossMarketView | None = None
    telegram: TelegramView | None = None
    consensus: ConsensusView | None = None

    @property
    def market_regime(self) -> MarketRegime | None:
        return self.regime.regime if self.regime is not None else None

    def suggested_direction(self) -> Direction | None:
        """Direction proposee par les lectures directionnelles, sans forcage.

        En cas d'egalite ou de contradiction, retourne ``None`` : le doute ne
        se tranche pas par un tirage au sort (CDC2 section 113).
        """
        votes: dict[Direction, float] = {Direction.BUY: 0.0, Direction.SELL: 0.0}
        sources = (
            (self.technical, 2.0),
            (self.historical, 1.0),
            (self.cross_market, 1.0),
            (self.telegram, 1.0),
        )
        for view, weight in sources:
            direction = getattr(view, "direction", None) if view is not None else None
            score = getattr(view, "score", None) if view is not None else None
            if direction is None or score is None:
                continue
            votes[direction] += weight * max(0.0, min(1.0, float(score)))

        if votes[Direction.BUY] == votes[Direction.SELL]:
            return None
        return Direction.BUY if votes[Direction.BUY] > votes[Direction.SELL] else Direction.SELL

    def components(
        self, direction: Direction | None, *, source: Any = None
    ) -> list[ComponentScore]:
        """Notes pretes pour le moteur de confiance.

        Les composantes directionnelles sont ramenees a l'appui qu'elles
        apportent a la direction envisagee ; les composantes de contexte
        (regime, macro, actualites) sont reprises telles quelles.

        ``source`` permet de declarer hors sujet ce qui n'a pas lieu d'etre :
        une opportunite generee par le systeme n'a pas de signal Telegram, et
        le consensus n'existe pas sans moteur d'IA actif. Sans cette
        distinction, ces composantes comptaient comme « donnee manquante » et
        plafonnaient la couverture sous le minimum exige : aucune decision ne
        pouvait plus aboutir, quelles que soient les autres lectures.
        """
        scores: list[ComponentScore] = []
        hors_sujet = self._hors_sujet(source)

        def add(
            component: ConfidenceComponent,
            view: Any,
            *,
            directional: bool,
        ) -> None:
            applicable = component not in hors_sujet
            if view is None:
                scores.append(
                    ComponentScore(
                        component=component,
                        score=None,
                        applicable=applicable,
                        detail=None if applicable else "Sans objet pour ce dossier.",
                    )
                )
                return
            raw = getattr(view, "score", None)
            view_direction = getattr(view, "direction", None) if directional else None
            scores.append(
                ComponentScore(
                    component=component,
                    score=aligned_score(raw, view_direction, direction),
                    detail=getattr(view, "detail", None),
                    direction=view_direction,
                    applicable=applicable,
                )
            )

        add(ConfidenceComponent.TECHNICAL, self.technical, directional=True)
        add(ConfidenceComponent.HISTORICAL, self.historical, directional=True)
        add(ConfidenceComponent.MARKET_REGIME, self.regime, directional=False)
        add(ConfidenceComponent.MACRO, self.macro, directional=True)
        add(ConfidenceComponent.NEWS, self.news, directional=False)
        add(ConfidenceComponent.CROSS_MARKET, self.cross_market, directional=True)
        add(ConfidenceComponent.TELEGRAM, self.telegram, directional=True)
        add(ConfidenceComponent.AI_CONSENSUS, self.consensus, directional=True)
        return scores

    def _hors_sujet(self, source: Any) -> set[ConfidenceComponent]:
        """Composantes qui ne s'appliquent pas a ce dossier.

        On ne declare hors sujet que ce qui l'est STRUCTURELLEMENT. Une
        composante simplement non calculee reste « manquante » : c'est une
        lacune, et elle doit peser.
        """
        exclues: set[ConfidenceComponent] = set()
        nom = getattr(source, "value", source)
        if nom is not None and str(nom) != "TELEGRAM" and self.telegram is None:
            # Aucun signal Telegram n'est en jeu : il n'y a rien a attendre.
            exclues.add(ConfidenceComponent.TELEGRAM)
        # Le consensus IA n'est PAS declare hors sujet quand il manque : sur un
        # dossier ou l'utilisateur a arme l'IA, son absence est une vraie
        # lacune et doit peser. Les composantes analytiques (historique, macro,
        # correlations) non plus : si elles ne sont pas calculees, la couverture
        # doit le montrer plutot que de le masquer.
        return exclues


__all__ = [
    "AnalysisBundle",
    "ConsensusView",
    "CrossMarketView",
    "HistoricalView",
    "MacroView",
    "NewsView",
    "PriceStructure",
    "QuoteView",
    "RegimeView",
    "TechnicalView",
    "TelegramView",
    "TradeLevels",
]
