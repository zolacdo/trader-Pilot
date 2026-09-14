"""Routes de marche : watchlist, symboles disponibles, scan, detail et bougies.

Toutes les routes sont protegees par ``require_device``. Aucune ne fabrique de
donnee : quand le broker ne repond pas ou qu'un instrument n'existe pas, la
reponse le dit explicitement (CDC2 sections 16 a 21).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.core import Device
from app.repositories import market_repo
from app.services import journal
from app.services.market_data.engine import (
    DEFAULT_BARS,
    MAX_BARS,
    SUPPORTED_TIMEFRAMES,
    MarketDataEngine,
    parse_timeframe,
)
from app.services.market_data.provider import market_engine
from app.services.market_data.watchlist import WatchlistService, watchlist_payload
from app.services.market_scanner.runner import run_scan, symbol_detail
from app.services.security.auth import require_device

router = APIRouter(tags=["market"])

NO_MARKET_SERVICE = "Aucun service de marché n'est attaché : MetaTrader 5 n'est pas disponible."


class WatchlistAddRequest(BaseModel):
    """Ajout d'un instrument. Le symbole est resolu aupres du broker."""

    symbol: str = Field(min_length=2, max_length=32)
    enabled: bool | None = None
    scan_priority: int | None = Field(default=None, ge=1, le=10, alias="scanPriority")
    allow_ai_trading: bool | None = Field(default=None, alias="allowAiTrading")
    allow_telegram_trading: bool | None = Field(default=None, alias="allowTelegramTrading")
    notify_news: bool | None = Field(default=None, alias="notifyNews")
    notify_opportunities: bool | None = Field(default=None, alias="notifyOpportunities")
    notify_volatility: bool | None = Field(default=None, alias="notifyVolatility")

    model_config = {"populate_by_name": True}


class WatchlistUpdateRequest(BaseModel):
    """Modification partielle d'une ligne de watchlist."""

    enabled: bool | None = None
    scan_priority: int | None = Field(default=None, ge=1, le=10, alias="scanPriority")
    allow_ai_trading: bool | None = Field(default=None, alias="allowAiTrading")
    allow_telegram_trading: bool | None = Field(default=None, alias="allowTelegramTrading")
    notify_news: bool | None = Field(default=None, alias="notifyNews")
    notify_opportunities: bool | None = Field(default=None, alias="notifyOpportunities")
    notify_volatility: bool | None = Field(default=None, alias="notifyVolatility")

    model_config = {"populate_by_name": True}


def _engine() -> MarketDataEngine:
    """Moteur de donnees actif, ou 503 explicite."""
    engine = market_engine()
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=NO_MARKET_SERVICE
        )
    return engine


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

@router.get("/market/watchlist")
async def list_watchlist(
    enabled_only: bool = Query(default=False, alias="enabledOnly"),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Instruments que TradePilot a le droit d'observer (CDC2 section 17)."""
    items = await market_repo.list_watchlist(session, enabled_only=enabled_only)
    return {
        "count": len(items),
        "items": [watchlist_payload(item) for item in items],
    }


@router.post("/market/watchlist", status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    payload: WatchlistAddRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Ajoute un instrument, apres confirmation de son existence chez le broker."""
    service = WatchlistService(_engine())
    options = payload.model_dump(exclude_none=True, exclude={"symbol"})
    item, resolution = await service.add(session, payload.symbol, **options)
    if item is None:
        raise HTTPException(
            status_code=422,  # entite non traitable : l'instrument n'existe pas
            detail={
                "message": resolution.message,
                "symbol": resolution.canonical,
                "suggestions": resolution.suggestions,
            },
        )
    await journal.record(
        session,
        event="watchlist_add",
        message=f"Instrument {item.canonical} ajouté à la watchlist",
        category="market",
    )
    return watchlist_payload(item)


@router.patch("/market/watchlist/{symbol}")
async def update_watchlist(
    symbol: str,
    payload: WatchlistUpdateRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Modifie les reglages d'un instrument deja surveille."""
    item = await market_repo.get_watchlist_item(session, symbol)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument absent de la watchlist : {symbol.upper()}.",
        )
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune modification fournie."
        )
    updated = await market_repo.update_watchlist_item(session, item, changes)
    return watchlist_payload(updated)


@router.delete("/market/watchlist/{symbol}")
async def remove_from_watchlist(
    symbol: str,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Retire un instrument de la watchlist."""
    removed = await market_repo.delete_watchlist_item(session, symbol)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument absent de la watchlist : {symbol.upper()}.",
        )
    await journal.record(
        session,
        event="watchlist_remove",
        message=f"Instrument {symbol.upper()} retiré de la watchlist",
        category="market",
    )
    return {"removed": True, "symbol": symbol.upper()}


@router.post("/market/watchlist/refresh")
async def refresh_watchlist(
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Revalide chaque instrument aupres du broker (disponibilite reelle)."""
    service = WatchlistService(_engine())
    items = await service.refresh(session)
    return {
        "count": len(items),
        "available": sum(1 for item in items if item.available),
        "items": [watchlist_payload(item) for item in items],
    }


# ---------------------------------------------------------------------------
# Catalogue de symboles
# ---------------------------------------------------------------------------

@router.get("/market/symbols")
async def available_symbols(
    search: str | None = Query(default=None, min_length=1, max_length=32),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Symboles reellement disponibles sur le compte, et suggestions."""
    engine = _engine()
    service = WatchlistService(engine)
    catalogue = await service.catalogue()
    payload: dict[str, Any] = {
        "brokerSymbolCount": len(await engine.available_symbols()),
        "instrumentCount": len(catalogue),
        "instruments": [
            {"canonical": canonical, "brokerSymbol": broker}
            for canonical, broker in sorted(catalogue.items())
        ],
        "suggested": [candidate.to_dict() for candidate in await service.suggested(session)],
    }
    if search:
        resolution = await service.resolve(session, search, persist=False)
        payload["search"] = {
            "query": search,
            "symbol": resolution.canonical,
            "brokerSymbol": resolution.broker_symbol,
            "available": resolution.available,
            "suggestions": resolution.suggestions,
            "message": resolution.message,
        }
    return payload


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

@router.get("/market/scan")
async def last_scan(
    limit: int = Query(default=50, ge=1, le=200),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Dernier etat connu de chaque instrument, sans relancer d'analyse."""
    snapshots = await market_repo.latest_snapshots(session, limit=limit)
    return {
        "count": len(snapshots),
        "items": [
            {
                "symbol": snapshot.symbol,
                "capturedAt": snapshot.captured_at.isoformat(),
                "bid": snapshot.bid,
                "ask": snapshot.ask,
                "spreadPoints": snapshot.spread_points,
                "regime": snapshot.regime.value,
                "trends": {
                    "D1": snapshot.trend_d1.value,
                    "H4": snapshot.trend_h4.value,
                    "H1": snapshot.trend_h1.value,
                },
                "technicalScore": snapshot.technical_score,
                "features": snapshot.features,
            }
            for snapshot in snapshots
        ],
    }


@router.post("/market/scan")
async def scan_market(
    limit: int | None = Query(default=None, ge=1, le=100),
    strategy: str | None = Query(default=None, max_length=32),
    persist: bool = Query(default=True),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Lance un scan local et deterministe de la watchlist (aucun appel IA)."""
    engine = _engine()
    results = await run_scan(session, engine, limit=limit, persist=persist, strategy=strategy)
    return {
        "count": len(results),
        "persisted": persist,
        "items": [result.to_dict() for result in results],
    }


# ---------------------------------------------------------------------------
# Detail d'un instrument
# ---------------------------------------------------------------------------

@router.get("/market/{symbol}/candles")
async def symbol_candles(
    symbol: str,
    timeframe: str = Query(default="H1"),
    bars: int = Query(default=DEFAULT_BARS, ge=5, le=MAX_BARS),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Bougies OHLC d'un instrument, servies par le cache memoire."""
    frame = parse_timeframe(timeframe)
    if frame is None or frame not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unité de temps inconnue : {timeframe}. "
                f"Valeurs acceptées : {', '.join(item.value for item in SUPPORTED_TIMEFRAMES)}."
            ),
        )
    engine = _engine()
    service = WatchlistService(engine)
    resolution = await service.resolve(session, symbol)
    if not resolution.available or resolution.broker_symbol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=resolution.message)
    candles = await engine.candles(resolution.broker_symbol, frame, bars)
    return {
        "symbol": resolution.canonical,
        "brokerSymbol": resolution.broker_symbol,
        "timeframe": frame.value,
        "count": len(candles),
        "candles": [candle.to_dict() for candle in candles],
    }


@router.get("/market/{symbol}")
async def market_detail(
    symbol: str,
    strategy: str | None = Query(default=None, max_length=32),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Detail complet : prix, état du marché, régime, technique, multi-timeframes."""
    engine = _engine()
    detail = await symbol_detail(session, symbol, engine, strategy=strategy)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument introuvable chez le broker : {symbol.upper()}.",
        )
    return detail


@router.get("/market/{symbol}/regimes")
async def symbol_regimes(
    symbol: str,
    limit: int = Query(default=50, ge=1, le=200),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Historique des changements de régime d'un instrument."""
    records = await market_repo.list_regimes(session, symbol, limit=limit)
    return {
        "symbol": symbol.upper(),
        "count": len(records),
        "items": [
            {
                "detectedAt": record.detected_at.isoformat(),
                "timeframe": record.timeframe.value,
                "regime": record.regime.value,
                "atr": record.atr,
                "atrRatio": record.atr_ratio,
                "detail": record.detail,
            }
            for record in records
        ],
    }


__all__ = ["router"]
