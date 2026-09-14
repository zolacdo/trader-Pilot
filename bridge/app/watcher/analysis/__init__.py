"""Analyses deterministes propres au Market Watcher (CDC3 sections 9 a 14).

Chaque module y est pur et testable seul : il recoit des bougies reelles et
rend une lecture chiffree. Aucun de ces modules n'appelle d'IA, n'ecrit en
base ni ne parle au reseau.
"""

from app.watcher.analysis.context import (
    DataQuality,
    FundamentalReading,
    MarketContext,
    NewsGuard,
    SentimentReading,
    build_context,
)
from app.watcher.analysis.liquidity import LiquidityReading, LiquidityZone, read_liquidity
from app.watcher.analysis.price_action import (
    CandleShape,
    PriceActionReading,
    read_price_action,
)
from app.watcher.analysis.volatility import VolatilityReading, read_volatility
from app.watcher.analysis.volume import VolumeReading, read_volume

__all__ = [
    "CandleShape",
    "DataQuality",
    "FundamentalReading",
    "LiquidityReading",
    "LiquidityZone",
    "MarketContext",
    "NewsGuard",
    "PriceActionReading",
    "SentimentReading",
    "VolatilityReading",
    "VolumeReading",
    "build_context",
    "read_liquidity",
    "read_price_action",
    "read_volatility",
    "read_volume",
]
