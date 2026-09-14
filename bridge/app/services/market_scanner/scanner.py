"""Scanner de marche deterministe (CDC2 section 18).

Le scanner passe en revue les instruments autorises et produit, pour chacun :
tendance, volatilite, momentum, structure, supports / resistances, regime,
anomalies, potentiel de setup et priorite d'analyse.

AUCUN appel a une intelligence artificielle n'est fait ici. Tout est calcule
localement, a partir des bougies du broker. L'IA intervient plus tard, sur les
seuls instruments que ce scanner a juges dignes d'attention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.models.enums import Direction
from app.models.intelligence import MarketRegime, Timeframe, TrendState
from app.services.market_data.engine import MarketDataEngine
from app.services.market_regime.detector import MarketRegimeDetector, RegimeAssessment
from app.services.mt5.interface import Candle, SymbolInfo
from app.services.technical_analysis.engine import TechnicalAnalysis, TechnicalAnalysisEngine
from app.services.technical_analysis.multi_timeframe import (
    DEFAULT_PROFILE,
    STATE_NO_TRIGGER,
    MultiTimeframeAnalyzer,
    MultiTimeframeView,
    TimeframeProfile,
    TimeframeRole,
)

# Poids du potentiel de setup. Leur somme fait 1.
WEIGHT_ALIGNMENT = 0.35
WEIGHT_TRIGGER = 0.20
WEIGHT_RISK_REWARD = 0.25
WEIGHT_REGIME = 0.20

# Ratio risque / rendement au-dela duquel le critere est considere au maximum.
RR_CEILING = 3.0

# Aptitude de chaque regime a porter un setup exploitable.
REGIME_QUALITY: dict[MarketRegime, float] = {
    MarketRegime.TRENDING_UP: 1.0,
    MarketRegime.TRENDING_DOWN: 1.0,
    MarketRegime.BREAKOUT: 0.9,
    MarketRegime.RANGING: 0.4,
    MarketRegime.HIGH_VOLATILITY: 0.3,
    MarketRegime.LOW_VOLATILITY: 0.3,
    MarketRegime.NEWS_DRIVEN: 0.2,
    MarketRegime.UNCERTAIN: 0.1,
}

# Seuils d'anomalie, exprimes en multiples d'ATR ou de spread declare.
ANOMALY_RANGE_ATR = 3.0
ANOMALY_GAP_ATR = 1.5
ANOMALY_SPREAD_FACTOR = 3.0
ANOMALY_ATR_RATIO = 2.5


def trading_session(moment: datetime) -> str:
    """Session de marche en cours, deduite de l'heure UTC."""
    hour = moment.astimezone(UTC).hour
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 16:
        return "OVERLAP"
    if 16 <= hour < 21:
        return "NEWYORK"
    return "ASIA"


@dataclass(slots=True)
class ScanResult:
    """Ce que le scanner a mesure sur un instrument."""

    symbol: str
    broker_symbol: str | None = None
    scanned_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    scan_priority: int = 5

    trend: TrendState = TrendState.NEUTRAL
    trend_d1: TrendState = TrendState.NEUTRAL
    trend_h4: TrendState = TrendState.NEUTRAL
    trend_h1: TrendState = TrendState.NEUTRAL
    structure: str = "UNDEFINED"
    volatility: float | None = None
    atr: float | None = None
    atr_ratio: float | None = None
    momentum: float | None = None
    rsi: float | None = None
    support: float | None = None
    resistance: float | None = None
    price: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread_points: int | None = None

    regime: MarketRegime = MarketRegime.UNCERTAIN
    regime_confidence: float = 0.0
    regime_detail: str = ""

    alignment: float = 0.0
    trigger: str | None = None
    anomalies: list[str] = field(default_factory=list)
    setup_potential: float = 0.0
    setup_direction: Direction | None = None
    risk_reward: float | None = None
    priority: float = 0.0

    reasons: list[str] = field(default_factory=list)
    error: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    view: MultiTimeframeView | None = None

    @property
    def usable(self) -> bool:
        return self.error is None and self.price is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "brokerSymbol": self.broker_symbol,
            "scannedAt": self.scanned_at.isoformat(),
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "spreadPoints": self.spread_points,
            "trend": self.trend.value,
            "trends": {
                "D1": self.trend_d1.value,
                "H4": self.trend_h4.value,
                "H1": self.trend_h1.value,
            },
            "structure": self.structure,
            "atr": self.atr,
            "atrRatio": self.atr_ratio,
            "volatility": self.volatility,
            "momentum": self.momentum,
            "rsi": self.rsi,
            "support": self.support,
            "resistance": self.resistance,
            "regime": self.regime.value,
            "regimeConfidence": self.regime_confidence,
            "regimeDetail": self.regime_detail,
            "alignment": self.alignment,
            "trigger": self.trigger,
            "anomalies": list(self.anomalies),
            "setupPotential": self.setup_potential,
            "setupDirection": self.setup_direction.value if self.setup_direction else None,
            "riskReward": self.risk_reward,
            "priority": self.priority,
            "scanPriority": self.scan_priority,
            "reasons": list(self.reasons),
            "error": self.error,
            "multiTimeframe": self.view.to_dict() if self.view else None,
        }


class MarketScanner:
    """Analyse locale et deterministe d'un instrument, puis d'une liste."""

    def __init__(
        self,
        data_engine: MarketDataEngine,
        technical: TechnicalAnalysisEngine | None = None,
        analyzer: MultiTimeframeAnalyzer | None = None,
        detector: MarketRegimeDetector | None = None,
        profile: TimeframeProfile | None = None,
        bars: int = 200,
    ) -> None:
        self._data = data_engine
        self._technical = technical or TechnicalAnalysisEngine()
        self._analyzer = analyzer or MultiTimeframeAnalyzer(self._technical)
        self._detector = detector or MarketRegimeDetector(self._technical)
        self._profile = profile or DEFAULT_PROFILE
        self._bars = max(60, int(bars))

    @property
    def profile(self) -> TimeframeProfile:
        return self._profile

    async def scan_symbol(
        self,
        symbol: str,
        broker_symbol: str | None = None,
        scan_priority: int = 5,
        news_pressure: bool = False,
    ) -> ScanResult:
        """Analyse complete d'un instrument. Aucune exception ne remonte."""
        target = broker_symbol or symbol
        result = ScanResult(
            symbol=symbol.upper(),
            broker_symbol=broker_symbol,
            scanned_at=self._data.now(),
            scan_priority=max(1, min(10, int(scan_priority))),
        )
        view = await self._analyzer.analyse(self._data, target, self._profile, self._bars)
        result.view = view
        reference = self._reference_analysis(view)
        if reference is None or not reference.usable:
            result.error = "Historique insuffisant : instrument non analysable."
            result.reasons.append(result.error)
            return result

        self._fill_technical(result, view, reference)
        quote = await self._data.quote(target)
        if quote is not None:
            result.spread_points = quote.spread_points
            result.bid = quote.bid
            result.ask = quote.ask
            if quote.mid is not None:
                result.price = quote.mid

        # Les bougies de reference sortent du cache : aucun appel supplementaire.
        candles = await self._data.candles(target, reference.timeframe, self._bars)
        assessment = self._detector.assess(
            result.symbol,
            reference.timeframe,
            candles,
            analysis=reference,
            news_pressure=news_pressure,
        )
        self._fill_regime(result, assessment)
        result.anomalies = self._anomalies(candles, reference, result, await self._data.symbol_info(target))
        self._score(result, view, reference)
        result.features = self._features(result, reference)
        return result

    async def scan_many(
        self, targets: list[tuple[str, str | None, int]], news_pressure: bool = False
    ) -> list[ScanResult]:
        """Scanne une liste ``(canonique, symbole broker, priorite)``."""
        results: list[ScanResult] = []
        for canonical, broker, priority in targets:
            results.append(
                await self.scan_symbol(canonical, broker, priority, news_pressure=news_pressure)
            )
        results.sort(key=lambda item: item.priority, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Construction du resultat
    # ------------------------------------------------------------------
    def _reference_analysis(self, view: MultiTimeframeView) -> TechnicalAnalysis | None:
        """Unite de temps de reference : la premiere de role STRUCTURE."""
        for verdict in view.verdicts:
            if (
                verdict.role is TimeframeRole.STRUCTURE
                and verdict.analysis is not None
                and verdict.analysis.usable
            ):
                return verdict.analysis
        for verdict in view.verdicts:
            if verdict.analysis is not None and verdict.analysis.usable:
                return verdict.analysis
        return None

    def _fill_technical(
        self, result: ScanResult, view: MultiTimeframeView, reference: TechnicalAnalysis
    ) -> None:
        result.price = reference.last_close
        result.trend = view.bias
        result.structure = reference.structure.label
        result.atr = reference.atr
        result.volatility = reference.volatility
        result.momentum = reference.momentum
        result.rsi = reference.rsi
        result.support = reference.levels.support
        result.resistance = reference.levels.resistance
        result.alignment = view.alignment
        result.trigger = view.trigger
        for frame, attribute in (
            (Timeframe.D1, "trend_d1"),
            (Timeframe.H4, "trend_h4"),
            (Timeframe.H1, "trend_h1"),
        ):
            analysis = view.analysis_for(frame)
            if analysis is not None and analysis.usable:
                setattr(result, attribute, analysis.trend)
        result.reasons.extend(reference.reasons)

    def _fill_regime(self, result: ScanResult, assessment: RegimeAssessment) -> None:
        result.regime = assessment.regime
        result.regime_confidence = assessment.confidence
        result.regime_detail = assessment.detail
        result.atr_ratio = assessment.atr_ratio

    def _anomalies(
        self,
        candles: list[Candle],
        reference: TechnicalAnalysis,
        result: ScanResult,
        info: SymbolInfo | None,
    ) -> list[str]:
        """Ecarts mesurables par rapport au comportement habituel."""
        anomalies: list[str] = []
        atr = reference.atr
        if atr and atr > 0 and len(candles) >= 2:
            last = candles[-1]
            if (last.high - last.low) > atr * ANOMALY_RANGE_ATR:
                anomalies.append("AMPLITUDE_EXTREME")
            if abs(last.open - candles[-2].close) > atr * ANOMALY_GAP_ATR:
                anomalies.append("GAP")
        if (
            info is not None
            and info.spread > 0
            and result.spread_points is not None
            and result.spread_points > info.spread * ANOMALY_SPREAD_FACTOR
        ):
            anomalies.append("SPREAD_ANORMAL")
        if result.atr_ratio is not None and result.atr_ratio >= ANOMALY_ATR_RATIO:
            anomalies.append("VOLATILITE_EXCEPTIONNELLE")
        return anomalies

    def _score(
        self, result: ScanResult, view: MultiTimeframeView, reference: TechnicalAnalysis
    ) -> None:
        """Potentiel de setup et priorite d'analyse, sur des criteres explicites."""
        if view.bias is TrendState.BULLISH:
            result.setup_direction = Direction.BUY
        elif view.bias is TrendState.BEARISH:
            result.setup_direction = Direction.SELL

        trigger_score = 0.0
        if result.trigger is not None and result.trigger != STATE_NO_TRIGGER:
            trigger_score = 1.0

        rr_score = 0.0
        if result.setup_direction is not None:
            result.risk_reward = reference.risk_reward(result.setup_direction)
            if result.risk_reward is not None:
                rr_score = min(1.0, result.risk_reward / RR_CEILING)

        regime_score = REGIME_QUALITY.get(result.regime, 0.1)
        potential = (
            view.alignment * WEIGHT_ALIGNMENT
            + trigger_score * WEIGHT_TRIGGER
            + rr_score * WEIGHT_RISK_REWARD
            + regime_score * WEIGHT_REGIME
        )
        result.setup_potential = round(min(1.0, max(0.0, potential)), 3)

        # La priorite melange l'interet technique et le reglage utilisateur.
        anomaly_bonus = 0.2 if result.anomalies else 0.0
        result.priority = round(
            min(
                1.0,
                result.setup_potential * 0.6
                + (result.scan_priority / 10.0) * 0.2
                + anomaly_bonus,
            ),
            3,
        )

    def _features(self, result: ScanResult, reference: TechnicalAnalysis) -> dict[str, Any]:
        """Caracteristiques normalisees, reutilisables par l'analyse historique."""
        return {
            "timeframe": reference.timeframe.value,
            "trendD1": result.trend_d1.value,
            "trendH4": result.trend_h4.value,
            "trendH1": result.trend_h1.value,
            "structure": result.structure,
            "regime": result.regime.value,
            "atr": result.atr,
            "atrRatio": result.atr_ratio,
            "rsi": result.rsi,
            "momentum": result.momentum,
            "volatility": result.volatility,
            "efficiency": reference.range_reading.efficiency,
            "distanceSupport": reference.distance_to_support(),
            "distanceResistance": reference.distance_to_resistance(),
            "spreadPoints": result.spread_points,
            "session": trading_session(result.scanned_at),
            "alignment": result.alignment,
            "trigger": result.trigger,
            "anomalies": list(result.anomalies),
            "setupPotential": result.setup_potential,
        }


__all__ = ["REGIME_QUALITY", "MarketScanner", "ScanResult", "trading_session"]
