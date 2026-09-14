"""Passage du scanner sur la watchlist, et detail d'un instrument.

Ce module relie le scanner deterministe (CDC2 section 18) a la base : il ecrit
un ``MarketSnapshot`` par instrument analyse et n'enregistre un regime que
lorsqu'il CHANGE (CDC2 section 21).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.intelligence import MarketSnapshot, Timeframe
from app.repositories import market_repo
from app.services.market_data.engine import MarketDataEngine
from app.services.market_data.provider import market_engine
from app.services.market_data.watchlist import WatchlistService
from app.services.market_scanner.scanner import MarketScanner, ScanResult
from app.services.technical_analysis.multi_timeframe import (
    TimeframeProfile,
    TimeframeRole,
    profile_for,
)

logger = get_logger(__name__)


def _snapshot_from(result: ScanResult) -> MarketSnapshot:
    """Traduit un resultat de scan en enregistrement de contexte."""
    return MarketSnapshot(
        symbol=result.symbol,
        captured_at=result.scanned_at,
        bid=result.bid,
        ask=result.ask,
        spread_points=result.spread_points,
        regime=result.regime,
        trend_d1=result.trend_d1,
        trend_h4=result.trend_h4,
        trend_h1=result.trend_h1,
        features=result.features,
        technical_score=result.setup_potential,
    )


async def persist_result(
    session: AsyncSession, result: ScanResult, timeframe: Timeframe
) -> MarketSnapshot | None:
    """Ecrit le snapshot et, le cas echeant, le changement de regime."""
    if not result.usable:
        return None
    snapshot = await market_repo.save_snapshot(session, _snapshot_from(result))
    await market_repo.record_regime_change(
        session,
        symbol=result.symbol,
        timeframe=timeframe,
        regime=result.regime,
        atr=result.atr,
        atr_ratio=result.atr_ratio,
        detail=result.regime_detail,
    )
    return snapshot


async def run_scan(
    session: AsyncSession,
    engine: MarketDataEngine | None = None,
    limit: int | None = None,
    persist: bool = True,
    strategy: str | None = None,
    news_pressure: bool = False,
) -> list[ScanResult]:
    """Scanne les instruments actifs et confirmes de la watchlist."""
    data_engine = engine or market_engine()
    if data_engine is None:
        logger.warning("Scan impossible : aucun service de marche attache")
        return []

    watchlist = WatchlistService(data_engine)
    items = await watchlist.scannable(session)
    if limit is not None:
        items = items[: max(1, int(limit))]
    if not items:
        return []

    profile = profile_for(strategy)
    scanner = MarketScanner(data_engine, profile=profile)
    targets = [(item.canonical, item.broker_symbol, item.scan_priority) for item in items]
    results = await scanner.scan_many(targets, news_pressure=news_pressure)

    if persist:
        reference = _reference_timeframe(profile)
        by_symbol = {item.canonical: item for item in items}
        for result in results:
            await persist_result(session, result, reference)
            item = by_symbol.get(result.symbol)
            if item is not None:
                await market_repo.mark_scanned(session, item, result.scanned_at)
    return results


def _reference_timeframe(profile: TimeframeProfile) -> Timeframe:
    """Unite de temps sur laquelle le regime est enregistre."""
    structure = profile.of_role(TimeframeRole.STRUCTURE)
    if structure:
        return structure[0]
    frames = profile.timeframes
    return frames[0] if frames else Timeframe.H1


async def symbol_detail(
    session: AsyncSession,
    symbol: str,
    engine: MarketDataEngine | None = None,
    strategy: str | None = None,
    news_pressure: bool = False,
) -> dict[str, Any] | None:
    """Detail complet d'un instrument : prix, regime, technique, multi-timeframes.

    Rend ``None`` quand le broker ne propose pas l'instrument : l'appelant doit
    alors le dire clairement, jamais inventer une analyse.
    """
    data_engine = engine or market_engine()
    if data_engine is None:
        return None

    watchlist = WatchlistService(data_engine)
    resolution = await watchlist.resolve(session, symbol)
    if not resolution.available or resolution.broker_symbol is None:
        return None

    profile = profile_for(strategy)
    scanner = MarketScanner(data_engine, profile=profile)
    item = await market_repo.get_watchlist_item(session, resolution.canonical)
    result = await scanner.scan_symbol(
        resolution.canonical,
        resolution.broker_symbol,
        scan_priority=item.scan_priority if item else 5,
        news_pressure=news_pressure,
    )
    state = await data_engine.market_state(resolution.broker_symbol)
    regimes = await market_repo.list_regimes(session, resolution.canonical, limit=10)

    timeframes: dict[str, Any] = {}
    if result.view is not None:
        for verdict in result.view.verdicts:
            if verdict.analysis is not None:
                timeframes[verdict.timeframe.value] = verdict.analysis.to_dict()

    return {
        "symbol": resolution.canonical,
        "brokerSymbol": resolution.broker_symbol,
        "inWatchlist": item is not None,
        "marketState": state.to_dict(),
        "metadata": resolution.info.to_dict() if resolution.info else None,
        "scan": result.to_dict(),
        "timeframes": timeframes,
        "regimeHistory": [
            {
                "detectedAt": record.detected_at.isoformat(),
                "timeframe": record.timeframe.value,
                "regime": record.regime.value,
                "atr": record.atr,
                "atrRatio": record.atr_ratio,
                "detail": record.detail,
            }
            for record in regimes
        ],
    }


__all__ = ["persist_result", "run_scan", "symbol_detail"]
