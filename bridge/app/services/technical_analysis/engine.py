"""Moteur d'analyse technique deterministe (CDC2 section 20).

Aucune intelligence artificielle ici : uniquement des mesures reproductibles
sur des bougies reelles. Ce moteur produit les chiffres ; l'IA, plus loin dans
la chaine, ne fait que les commenter.

Quand l'historique est insuffisant, les champs concernes restent a ``None``.
Jamais d'estimation, jamais de valeur de remplissage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.enums import Direction
from app.models.intelligence import Timeframe, TrendState
from app.services.mt5.interface import Candle
from app.services.technical_analysis import indicators
from app.services.technical_analysis.structure import (
    STRUCTURE_UNDEFINED,
    BreakEvent,
    Levels,
    RangeReading,
    StructureReading,
    SwingPoint,
    detect_break,
    detect_breakout,
    detect_pullback,
    find_swings,
    levels_around,
    read_range,
    read_structure,
)

# Nombre de points de score au-dela duquel une tendance est reconnue.
TREND_THRESHOLD = 2
TREND_MAX_SCORE = 5

# Pente minimale, en pourcentage du prix par barre, pour compter comme
# directionnelle. En dessous, la pente n'est pas significative.
SLOPE_EPSILON = 0.01

# Marge ajoutee sous le swing protecteur, en fraction d'ATR.
STOP_BUFFER_ATR = 0.25
# Stop de repli quand aucun swing protecteur n'est utilisable.
DEFAULT_STOP_ATR = 1.5


@dataclass(slots=True)
class TechnicalAnalysis:
    """Photographie chiffree d'un instrument sur un timeframe donne."""

    symbol: str
    timeframe: Timeframe
    candles_used: int = 0
    last_close: float | None = None
    last_time: datetime | None = None

    atr: float | None = None
    atr_ratio: float | None = None  # ATR rapporte au prix, en pourcentage
    rsi: float | None = None
    ma_fast: float | None = None
    ma_slow: float | None = None
    momentum: float | None = None
    volatility: float | None = None
    efficiency: float | None = None
    slope: float | None = None

    trend: TrendState = TrendState.NEUTRAL
    trend_score: int = 0
    trend_strength: float = 0.0

    structure: StructureReading = field(default_factory=StructureReading)
    swings: list[SwingPoint] = field(default_factory=list)
    levels: Levels = field(default_factory=Levels)
    range_reading: RangeReading = field(default_factory=RangeReading)
    break_event: BreakEvent | None = None
    breakout: str | None = None
    pullback: float | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Vrai quand les mesures de base ont pu etre calculees."""
        return self.last_close is not None and self.atr is not None

    @property
    def change_of_character(self) -> bool:
        return self.break_event is not None and self.break_event.kind == "CHOCH"

    @property
    def break_of_structure(self) -> bool:
        return self.break_event is not None and self.break_event.kind == "BOS"

    def distance_to_support(self) -> float | None:
        if self.last_close is None or self.levels.support is None:
            return None
        return self.last_close - self.levels.support

    def distance_to_resistance(self) -> float | None:
        if self.last_close is None or self.levels.resistance is None:
            return None
        return self.levels.resistance - self.last_close

    def stop_loss_hint(self, direction: Direction) -> float | None:
        """Stop protecteur : dernier swing oppose, ou repli sur l'ATR."""
        if self.last_close is None or self.atr is None or self.atr <= 0:
            return None
        buffer_ = self.atr * STOP_BUFFER_ATR
        if direction is Direction.BUY:
            swing = self.structure.last_low
            if swing is not None and swing.price < self.last_close:
                return swing.price - buffer_
            return self.last_close - self.atr * DEFAULT_STOP_ATR
        swing = self.structure.last_high
        if swing is not None and swing.price > self.last_close:
            return swing.price + buffer_
        return self.last_close + self.atr * DEFAULT_STOP_ATR

    def stop_distance(self, direction: Direction) -> float | None:
        """Distance de SL potentielle, en unites de prix."""
        stop = self.stop_loss_hint(direction)
        if stop is None or self.last_close is None:
            return None
        return abs(self.last_close - stop)

    def target_hint(self, direction: Direction) -> float | None:
        """Objectif issu du premier niveau oppose. Jamais invente."""
        if direction is Direction.BUY:
            return self.levels.resistance
        return self.levels.support

    def risk_reward(self, direction: Direction) -> float | None:
        """Ratio risque / rendement vers le premier niveau oppose."""
        risk = self.stop_distance(direction)
        target = self.target_hint(direction)
        if risk is None or risk <= 0 or target is None or self.last_close is None:
            return None
        reward = (
            target - self.last_close if direction is Direction.BUY else self.last_close - target
        )
        if reward <= 0:
            return None
        return round(reward / risk, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "candlesUsed": self.candles_used,
            "lastClose": self.last_close,
            "lastTime": self.last_time.isoformat() if self.last_time else None,
            "atr": self.atr,
            "atrRatio": self.atr_ratio,
            "rsi": self.rsi,
            "maFast": self.ma_fast,
            "maSlow": self.ma_slow,
            "momentum": self.momentum,
            "volatility": self.volatility,
            "efficiency": self.efficiency,
            "slope": self.slope,
            "trend": self.trend.value,
            "trendScore": self.trend_score,
            "trendStrength": self.trend_strength,
            "structure": self.structure.to_dict(),
            "levels": self.levels.to_dict(),
            "range": self.range_reading.to_dict(),
            "breakEvent": self.break_event.to_dict() if self.break_event else None,
            "breakOfStructure": self.break_of_structure,
            "changeOfCharacter": self.change_of_character,
            "breakout": self.breakout,
            "pullback": self.pullback,
            "distanceToSupport": self.distance_to_support(),
            "distanceToResistance": self.distance_to_resistance(),
            "buy": {
                "stopLoss": self.stop_loss_hint(Direction.BUY),
                "stopDistance": self.stop_distance(Direction.BUY),
                "target": self.target_hint(Direction.BUY),
                "riskReward": self.risk_reward(Direction.BUY),
            },
            "sell": {
                "stopLoss": self.stop_loss_hint(Direction.SELL),
                "stopDistance": self.stop_distance(Direction.SELL),
                "target": self.target_hint(Direction.SELL),
                "riskReward": self.risk_reward(Direction.SELL),
            },
            "reasons": list(self.reasons),
        }


class TechnicalAnalysisEngine:
    """Calcule une ``TechnicalAnalysis`` a partir d'une serie de bougies."""

    def __init__(
        self,
        atr_period: int = 14,
        rsi_period: int = 14,
        fast_period: int = 20,
        slow_period: int = 50,
        swing_strength: int = 2,
        range_lookback: int = 40,
        momentum_period: int = 10,
    ) -> None:
        self.atr_period = max(2, int(atr_period))
        self.rsi_period = max(2, int(rsi_period))
        self.fast_period = max(2, int(fast_period))
        self.slow_period = max(self.fast_period + 1, int(slow_period))
        self.swing_strength = max(1, int(swing_strength))
        self.range_lookback = max(10, int(range_lookback))
        self.momentum_period = max(2, int(momentum_period))

    @property
    def minimum_candles(self) -> int:
        """Nombre de bougies en dessous duquel l'analyse n'a pas de sens."""
        return max(self.slow_period + 1, self.atr_period + 2, self.swing_strength * 2 + 3)

    def analyse(
        self, symbol: str, timeframe: Timeframe, candles: list[Candle]
    ) -> TechnicalAnalysis:
        """Analyse complete. Une serie vide rend un resultat vide, pas une erreur."""
        result = TechnicalAnalysis(symbol=symbol, timeframe=timeframe, candles_used=len(candles))
        if not candles:
            result.reasons.append("Aucune bougie disponible pour cet instrument.")
            return result

        series = indicators.closes(candles)
        last = candles[-1]
        result.last_close = last.close
        result.last_time = last.time

        result.atr = indicators.atr(candles, self.atr_period)
        if result.atr is not None and last.close:
            result.atr_ratio = result.atr / abs(last.close) * 100.0
        result.rsi = indicators.rsi(series, self.rsi_period)
        result.ma_fast = indicators.sma(series, self.fast_period)
        result.ma_slow = indicators.sma(series, self.slow_period)
        result.momentum = indicators.momentum(series, self.momentum_period)
        result.volatility = indicators.volatility(series, min(20, max(2, len(series) - 1)))
        result.efficiency = indicators.efficiency_ratio(series, min(20, max(2, len(series) - 1)))
        result.slope = indicators.normalised_slope(series, self.slow_period)

        result.swings = find_swings(candles, self.swing_strength)
        result.structure = read_structure(result.swings)
        tolerance = result.atr * 0.35 if result.atr else None
        result.levels = levels_around(result.swings, last.close, tolerance)
        result.range_reading = read_range(candles, self.range_lookback)
        result.break_event = detect_break(candles, result.swings, result.structure)
        result.breakout = detect_breakout(candles, result.atr, self.range_lookback)

        self._score_trend(result)
        result.pullback = detect_pullback(
            candles, result.structure, bullish=result.trend is TrendState.BULLISH
        )
        self._explain(result)
        return result

    def _score_trend(self, result: TechnicalAnalysis) -> None:
        """Score entier de -5 a +5, additionne a partir de criteres explicites."""
        score = 0
        if result.structure.bullish:
            score += 2
        elif result.structure.bearish:
            score -= 2
        if result.last_close is not None and result.ma_slow is not None:
            score += 1 if result.last_close > result.ma_slow else -1
        if result.ma_fast is not None and result.ma_slow is not None:
            score += 1 if result.ma_fast > result.ma_slow else -1
        if result.slope is not None:
            if result.slope > SLOPE_EPSILON:
                score += 1
            elif result.slope < -SLOPE_EPSILON:
                score -= 1
        result.trend_score = score
        if score >= TREND_THRESHOLD:
            result.trend = TrendState.BULLISH
        elif score <= -TREND_THRESHOLD:
            result.trend = TrendState.BEARISH
        else:
            result.trend = TrendState.NEUTRAL
        result.trend_strength = round(min(1.0, abs(score) / TREND_MAX_SCORE), 3)

    def _explain(self, result: TechnicalAnalysis) -> None:
        """Justifications lisibles, destinees a l'utilisateur (en francais)."""
        if result.structure.label != STRUCTURE_UNDEFINED:
            result.reasons.append(f"Structure {result.structure.label}.")
        if result.break_event is not None:
            kind = "Break of structure" if result.break_of_structure else "Change of character"
            sens = "haussier" if result.break_event.direction == "UP" else "baissier"
            result.reasons.append(f"{kind} {sens} sur {result.break_event.level}.")
        if result.breakout:
            sens = "haussier" if result.breakout == "UP" else "baissier"
            result.reasons.append(f"Breakout {sens} des bornes récentes.")
        if result.range_reading.is_range:
            result.reasons.append("Marché en range : efficience du mouvement faible.")
        if result.pullback is not None:
            result.reasons.append(f"Repli de {round(result.pullback * 100)} % de la dernière impulsion.")
        if result.rsi is not None:
            if result.rsi >= 70:
                result.reasons.append(f"RSI à {round(result.rsi, 1)} : zone de surachat.")
            elif result.rsi <= 30:
                result.reasons.append(f"RSI à {round(result.rsi, 1)} : zone de survente.")
        if not result.reasons:
            result.reasons.append("Aucun élément technique marquant sur cette unité de temps.")


# Moteur par defaut, sans etat : il peut etre partage sans risque.
technical_engine = TechnicalAnalysisEngine()

__all__ = ["TechnicalAnalysis", "TechnicalAnalysisEngine", "technical_engine"]
