"""Moteur de decision, garde-fous, coupe-circuit et shadow mode (CDC2)."""

from app.services.decision.circuit_breaker import (
    BreakerLimits,
    BreakerReason,
    BreakerState,
    CircuitBreaker,
    circuit_breaker,
)
from app.services.decision.context import DecisionContext, DecisionThresholds
from app.services.decision.engine import (
    DecisionEngine,
    DecisionOutcome,
    decision_engine,
    position_risk_multiplier,
)
from app.services.decision.guards import GuardCode, GuardVerdict, run_guards
from app.services.decision.inputs import (
    AnalysisBundle,
    ConsensusView,
    CrossMarketView,
    HistoricalView,
    MacroView,
    NewsView,
    PriceStructure,
    QuoteView,
    RegimeView,
    TechnicalView,
    TelegramView,
    TradeLevels,
)
from app.services.decision.shadow import (
    ShadowEngine,
    ShadowReport,
    ShadowStats,
    build_report,
    build_shadow_trade,
    close_shadow_trade,
    compute_stats,
    outcome_for,
)

__all__ = [
    "AnalysisBundle",
    "BreakerLimits",
    "BreakerReason",
    "BreakerState",
    "CircuitBreaker",
    "ConsensusView",
    "CrossMarketView",
    "DecisionContext",
    "DecisionEngine",
    "DecisionOutcome",
    "DecisionThresholds",
    "GuardCode",
    "GuardVerdict",
    "HistoricalView",
    "MacroView",
    "NewsView",
    "PriceStructure",
    "QuoteView",
    "RegimeView",
    "ShadowEngine",
    "ShadowReport",
    "ShadowStats",
    "TechnicalView",
    "TelegramView",
    "TradeLevels",
    "build_report",
    "build_shadow_trade",
    "circuit_breaker",
    "close_shadow_trade",
    "compute_stats",
    "decision_engine",
    "outcome_for",
    "position_risk_multiplier",
    "run_guards",
]
