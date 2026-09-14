"""Familles de strategies et registre (CDC2 section 45)."""

from app.services.strategies.base import (
    FAMILY_LABELS,
    StrategyFamily,
    StrategyProposal,
    TradingStrategy,
)
from app.services.strategies.families import (
    BreakoutStrategy,
    MeanReversionStrategy,
    PullbackStrategy,
    TrendFollowingStrategy,
)
from app.services.strategies.registry import (
    AMBIGUITY_GAP,
    StrategyRegistry,
    default_strategies,
    select_best,
    strategy_registry,
)

__all__ = [
    "AMBIGUITY_GAP",
    "FAMILY_LABELS",
    "BreakoutStrategy",
    "MeanReversionStrategy",
    "PullbackStrategy",
    "StrategyFamily",
    "StrategyProposal",
    "StrategyRegistry",
    "TradingStrategy",
    "TrendFollowingStrategy",
    "default_strategies",
    "select_best",
    "strategy_registry",
]
