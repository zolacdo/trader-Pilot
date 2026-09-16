"""Routes du AI Market Watcher (CDC3 sections 59 et 60).

Elles observent et declenchent des analyses. Aucune n'envoie d'ordre : le
watcher n'en est structurellement pas capable.

Toutes exigent un appareil appaire, comme le reste de l'API du Bridge.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.core import Device, utcnow
from app.models.enums import Direction
from app.services import journal
from app.services.market_data.provider import market_engine
from app.services.security.auth import require_device
from app.services.trading.symbol_resolver import SymbolResolver
from app.watcher import performance, repository
from app.watcher.config import load_config, update_config
from app.watcher.models import WatcherStatus
from app.watcher.publisher import ChannelNotFound, ChannelNotWritable
from app.watcher.scheduler import watcher_scheduler

router = APIRouter(prefix="/watcher", tags=["watcher"])

MAX_WINDOW_DAYS = 365


class SettingsRequest(BaseModel):
    """Reglages a modifier. Seules les cles fournies sont ecrites."""

    changes: dict[str, Any]


@router.get("/health", summary="Etat du Market Watcher")
async def health(device: Device = Depends(require_device)) -> dict[str, Any]:
    """Etat des boucles, du canal Telegram et de la configuration courante."""
    return await watcher_scheduler.health()


@router.get("/markets", summary="Derniere analyse de chaque instrument")
async def markets(
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    analyses = await repository.latest_analyses(session)
    return {
        "items": [analysis.to_dict() for analysis in analyses],
        "resolved": dict(watcher_scheduler.state.resolved_symbols),
        "unavailable": list(watcher_scheduler.state.unavailable_symbols),
    }


@router.get("/markets/{symbol}", summary="Fiche complete d'un instrument")
async def market_detail(
    symbol: str,
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    canonical = symbol.strip().upper()
    analysis = await repository.last_analysis(session, canonical)
    signals = await repository.list_signals(session, symbol=canonical, limit=20)
    if analysis is None and not signals:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Aucune analyse enregistrée pour {canonical}.",
        )
    return {
        "symbol": canonical,
        "lastAnalysis": analysis.to_dict() if analysis else None,
        "signals": [signal.to_dict() for signal in signals],
    }


@router.get("/signals", summary="Historique des signaux")
async def signals(
    symbol: str | None = None,
    direction: Direction | None = None,
    signal_status: WatcherStatus | None = Query(default=None, alias="status"),
    days: int = Query(default=30, ge=1, le=MAX_WINDOW_DAYS),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    rows = await repository.list_signals(
        session,
        symbol=symbol,
        direction=direction,
        status=signal_status,
        since=utcnow() - timedelta(days=days),
        limit=limit,
        offset=offset,
    )
    return {"items": [row.to_dict() for row in rows], "count": len(rows)}


@router.get("/signals/active", summary="Signaux encore suivis")
async def active_signals(
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    rows = await repository.open_signals(session)
    return {"items": [row.to_dict() for row in rows], "count": len(rows)}


@router.get("/signals/{signal_id}", summary="Detail d'un signal et son historique")
async def signal_detail(
    signal_id: int,
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    signal = await repository.get_signal(session, signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Signal introuvable."
        )
    events = await repository.events_for(session, signal_id)
    return {"signal": signal.to_dict(), "events": [event.to_dict() for event in events]}


@router.get("/performance", summary="Statistiques de performance")
async def performance_report(
    days: int = Query(default=30, ge=1, le=MAX_WINDOW_DAYS),
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    report = await performance.compute(session, window_days=days)
    # La bande mesuree sous le seuil vient avec : c'est la comparaison des deux
    # qui dit si le seuil merite de descendre, et une mesure que personne ne
    # peut lire ne sert a rien.
    shadow = await performance.compute(session, window_days=days, shadow=True)
    return {
        "report": report.to_dict(),
        "summary": performance.daily_digest(report),
        "shadowBand": shadow.to_dict(),
        "shadowSummary": performance.daily_digest(shadow),
    }


@router.post("/analysis/{symbol}", summary="Analyser un instrument maintenant")
async def analyse_now(
    symbol: str,
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    """Analyse immediate d'un instrument, sans attendre le prochain tour."""
    canonical = symbol.strip().upper()
    engine = market_engine()
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Aucune source de marché n'est attachée pour le moment.",
        )
    resolver = SymbolResolver(engine.service)
    resolved = await resolver.resolve(session, canonical)
    if resolved is None:
        suggestions = await resolver.suggestions(canonical)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"{canonical} n'existe pas chez ce broker."
                + (f" Proches : {', '.join(suggestions)}." if suggestions else "")
            ),
        )
    config = await load_config(session)
    outcome = await watcher_scheduler.engine.analyse(
        session, engine, canonical, resolved.broker_symbol, config
    )
    return outcome.to_dict()


@router.post("/run/{target}", summary="Declencher une boucle immediatement")
async def run_loop(
    target: str,
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    """``analysis``, ``lifecycle``, ``news`` ou ``maintenance``."""
    actions: dict[str, Any] = {
        "analysis": watcher_scheduler.run_analysis_once,
        "lifecycle": watcher_scheduler.run_lifecycle_once,
        "news": watcher_scheduler.run_news_once,
        "maintenance": watcher_scheduler.run_maintenance_once,
    }
    action = actions.get(target.strip().lower())
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Cible inconnue : {target}. Attendu : {', '.join(sorted(actions))}.",
        )
    result = await action()
    await journal.log(
        event="watcher_manual_run",
        message=f"Boucle « {target} » du watcher déclenchée manuellement",
        category="system",
    )
    if isinstance(result, list):
        return {"target": target, "outcomes": [item.to_dict() for item in result]}
    return {"target": target, "result": result}


@router.get("/settings", summary="Configuration du watcher")
async def read_settings(
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    config = await load_config(session, refresh=True)
    return {"settings": config.to_dict()}


@router.put("/settings", summary="Modifier la configuration du watcher")
async def write_settings(
    payload: SettingsRequest,
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    try:
        config = await update_config(session, payload.changes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    # Un changement de canal doit etre pris en compte sans redemarrage.
    if "telegram_channel" in payload.changes or "telegram_channel_id" in payload.changes:
        watcher_scheduler.publisher.forget()
    await journal.log(
        event="watcher_settings_updated",
        message=f"Réglages du watcher modifiés : {', '.join(sorted(payload.changes))}",
        category="system",
    )
    return {"settings": config.to_dict()}


@router.post("/telegram/resolve", summary="Retrouver le canal Telegram cible")
async def resolve_channel(
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    """Verifie que le canal existe et que le compte peut y publier."""
    config = await load_config(session, refresh=True)
    publisher = watcher_scheduler.publisher
    publisher.forget()
    try:
        target = await publisher.resolve(session, config, refresh=True)
    except ChannelNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChannelNotWritable as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Telegram indisponible : {exc}",
        ) from exc
    return {"channel": target.to_dict()}


__all__ = ["router"]
