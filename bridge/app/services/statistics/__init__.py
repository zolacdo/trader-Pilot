"""Statistiques de trading calculees depuis les trades reellement fermes."""

from __future__ import annotations

from app.services.statistics.service import (
    by_channel,
    by_day,
    by_hour,
    by_symbol,
    compare_channels,
    daily_summary,
    global_statistics,
)

__all__ = [
    "by_channel",
    "by_day",
    "by_hour",
    "by_symbol",
    "compare_channels",
    "daily_summary",
    "global_statistics",
]
