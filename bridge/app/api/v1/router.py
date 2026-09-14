"""Agregation des routes de l'API v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    channels,
    decisions,
    intelligence,
    market,
    news,
    notifications,
    patterns,
    settings,
    signals,
    stats,
    system,
    telegram,
    trading,
    watcher,
    websocket,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(system.router)
api_router.include_router(telegram.router)
api_router.include_router(channels.router)
api_router.include_router(signals.router)
api_router.include_router(trading.router)
api_router.include_router(settings.router)
api_router.include_router(stats.router)
api_router.include_router(ai.router)
api_router.include_router(market.router)
api_router.include_router(patterns.router)
api_router.include_router(news.router)
api_router.include_router(decisions.router)
api_router.include_router(notifications.router)
api_router.include_router(intelligence.router)
# AI Market Watcher (CDC3) : sous-systeme autonome, monte sur /watcher.
api_router.include_router(watcher.router)

# Le WebSocket est monte a la racine de l'API : /api/v1/ws
api_router.include_router(websocket.router)

__all__ = ["api_router"]
