"""Detecteur de regime de marche (CDC2 section 21).

Le regime est deduit de mesures, pas d'une impression : volatilite relative
(ATR court rapporte a l'ATR long), efficience du mouvement, structure et
cassures. Le moteur de strategie s'en sert pour adapter son comportement.

NEWS_DRIVEN n'est jamais devine : il faut qu'une pression d'actualite soit
transmise par l'appelant (calendrier economique ou flux d'actualites).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.models.intelligence import MarketRegime, Timeframe, TrendState
from app.services.mt5.interface import Candle
from app.services.technical_analysis import indicators
from app.services.technical_analysis.engine import TechnicalAnalysis, TechnicalAnalysisEngine

if TYPE_CHECKING:  # pragma: no cover - uniquement pour le typage
    from app.services.market_data.engine import MarketDataEngine

# Seuils de volatilite relative (ATR court / ATR de reference).
HIGH_VOLATILITY_RATIO = 1.8
BREAKOUT_VOLATILITY_RATIO = 1.2
NEWS_VOLATILITY_RATIO = 1.5
LOW_VOLATILITY_RATIO = 0.6

# Force de tendance minimale pour parler de tendance etablie.
TRENDING_STRENGTH = 0.6

# Fenetre de reference pour l'ATR long.
REFERENCE_PERIOD = 100


@dataclass(slots=True)
class RegimeAssessment:
    """Regime detecte et les chiffres qui l'ont produit."""

    symbol: str
    timeframe: Timeframe
    regime: MarketRegime = MarketRegime.UNCERTAIN
    confidence: float = 0.0
    atr: float | None = None
    atr_ratio: float | None = None
    detail: str = ""
    features: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "regime": self.regime.value,
            "confidence": self.confidence,
            "atr": self.atr,
            "atrRatio": self.atr_ratio,
            "detail": self.detail,
            "features": dict(self.features),
        }


class MarketRegimeDetector:
    """Classe un instrument dans l'un des huit regimes du CDC2."""

    def __init__(
        self,
        technical: TechnicalAnalysisEngine | None = None,
        reference_period: int = REFERENCE_PERIOD,
    ) -> None:
        self._technical = technical or TechnicalAnalysisEngine()
        self.reference_period = max(20, int(reference_period))

    async def detect(
        self,
        data_engine: MarketDataEngine,
        symbol: str,
        timeframe: Timeframe = Timeframe.H1,
        bars: int = 250,
        news_pressure: bool = False,
    ) -> RegimeAssessment:
        """Recupere les bougies puis evalue le regime."""
        candles = await data_engine.candles(symbol, timeframe, bars)
        return self.assess(symbol, timeframe, candles, news_pressure=news_pressure)

    def assess(
        self,
        symbol: str,
        timeframe: Timeframe,
        candles: list[Candle],
        analysis: TechnicalAnalysis | None = None,
        news_pressure: bool = False,
    ) -> RegimeAssessment:
        """Evaluation deterministe a partir d'une serie de bougies."""
        result = RegimeAssessment(symbol=symbol, timeframe=timeframe)
        reading = analysis or self._technical.analyse(symbol, timeframe, candles)
        if not reading.usable:
            result.detail = "Historique insuffisant : régime indéterminé."
            result.features = {"candles": len(candles)}
            return result

        result.atr = reading.atr
        reference = indicators.atr(candles, min(self.reference_period, max(2, len(candles) - 2)))
        if reference and reference > 0 and reading.atr is not None:
            result.atr_ratio = round(reading.atr / reference, 3)
        result.features = self._features(reading, result.atr_ratio, news_pressure)
        self._classify(result, reading, news_pressure)
        return result

    # ------------------------------------------------------------------
    # Regles de classement, appliquees dans cet ordre exact
    # ------------------------------------------------------------------
    def _classify(
        self, result: RegimeAssessment, reading: TechnicalAnalysis, news_pressure: bool
    ) -> None:
        ratio = result.atr_ratio

        if news_pressure and ratio is not None and ratio >= NEWS_VOLATILITY_RATIO:
            result.regime = MarketRegime.NEWS_DRIVEN
            result.confidence = 0.7
            result.detail = f"Actualité en cours et volatilité multipliée par {ratio}."
            return

        if reading.breakout is not None and (ratio is None or ratio >= BREAKOUT_VOLATILITY_RATIO):
            result.regime = MarketRegime.BREAKOUT
            result.confidence = 0.65 if ratio is None else min(1.0, round(ratio / 2.0, 3))
            sens = "haussier" if reading.breakout == "UP" else "baissier"
            result.detail = f"Sortie de range {sens} confirmée par l'expansion de l'ATR."
            return

        if ratio is not None and ratio >= HIGH_VOLATILITY_RATIO:
            result.regime = MarketRegime.HIGH_VOLATILITY
            result.confidence = min(1.0, round(ratio / 3.0, 3))
            result.detail = f"ATR courant {ratio} fois supérieur à sa référence."
            return

        if (
            reading.trend is not TrendState.NEUTRAL
            and reading.trend_strength >= TRENDING_STRENGTH
            and not reading.range_reading.is_range
        ):
            hausse = reading.trend is TrendState.BULLISH
            result.regime = MarketRegime.TRENDING_UP if hausse else MarketRegime.TRENDING_DOWN
            result.confidence = reading.trend_strength
            sens = "haussière" if hausse else "baissière"
            result.detail = f"Tendance {sens} confirmée par la structure et les moyennes."
            return

        if reading.range_reading.is_range:
            result.regime = MarketRegime.RANGING
            efficiency = reading.range_reading.efficiency
            result.confidence = round(1.0 - (efficiency or 0.0), 3)
            result.detail = "Marché sans direction nette : le prix revient sur ses pas."
            return

        if ratio is not None and ratio <= LOW_VOLATILITY_RATIO:
            result.regime = MarketRegime.LOW_VOLATILITY
            result.confidence = round(1.0 - ratio, 3)
            result.detail = f"Volatilité comprimée : ATR à {ratio} fois sa référence."
            return

        result.regime = MarketRegime.UNCERTAIN
        result.confidence = 0.0
        result.detail = "Aucun critère ne domine : régime incertain."

    def _features(
        self, reading: TechnicalAnalysis, ratio: float | None, news_pressure: bool
    ) -> dict[str, Any]:
        return {
            "trend": reading.trend.value,
            "trendStrength": reading.trend_strength,
            "structure": reading.structure.label,
            "efficiency": reading.range_reading.efficiency,
            "isRange": reading.range_reading.is_range,
            "breakout": reading.breakout,
            "changeOfCharacter": reading.change_of_character,
            "atr": reading.atr,
            "atrRatio": ratio,
            "rsi": reading.rsi,
            "momentum": reading.momentum,
            "volatility": reading.volatility,
            "newsPressure": news_pressure,
        }


# Detecteur par defaut, sans etat.
regime_detector = MarketRegimeDetector()

__all__ = [
    "HIGH_VOLATILITY_RATIO",
    "LOW_VOLATILITY_RATIO",
    "MarketRegimeDetector",
    "RegimeAssessment",
    "regime_detector",
]
