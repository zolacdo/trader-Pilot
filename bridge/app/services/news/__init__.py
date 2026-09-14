"""Moteur d'actualites TradePilot (CDC2 sections 27 a 32 et 35)."""

from __future__ import annotations

from app.services.news.dedup import NewsDeduplicator, similarity, verification_for
from app.services.news.engine import CollectionReport, NewsEngine, news_engine
from app.services.news.providers import (
    NewsProvider,
    NewsProviderError,
    NewsSourceProtected,
    RawNewsItem,
    RssNewsProvider,
)
from app.services.news.relevance import NewsRelevanceEngine, RelevanceResult
from app.services.news.risk_mode import BlackoutConfig, is_in_news_blackout
from app.services.news.sources import NewsOptions, NewsSource, default_sources

__all__ = [
    "BlackoutConfig",
    "CollectionReport",
    "NewsDeduplicator",
    "NewsEngine",
    "NewsOptions",
    "NewsProvider",
    "NewsProviderError",
    "NewsRelevanceEngine",
    "NewsSource",
    "NewsSourceProtected",
    "RawNewsItem",
    "RelevanceResult",
    "RssNewsProvider",
    "default_sources",
    "is_in_news_blackout",
    "news_engine",
    "similarity",
    "verification_for",
]
