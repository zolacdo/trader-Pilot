"""Routes actualites et calendrier economique (CDC2 sections 27 a 35).

Aucune de ces routes ne declenche un ordre. Elles exposent ce que le moteur a
collecte, avec ses sources et ses incertitudes, et permettent a l'utilisateur
de configurer lui-meme ses flux.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.database.session import get_session
from app.models.core import Device, as_utc
from app.models.intelligence import EconomicEvent, NewsEvent, NewsImpact
from app.repositories import news_repo
from app.services.economic_calendar.engine import NO_SOURCE_MESSAGE, economic_calendar_engine
from app.services.news.engine import news_engine
from app.services.news.sources import NewsOptions, NewsSource, load_options, load_sources
from app.services.news.sources import save_options as store_options
from app.services.news.sources import save_sources as store_sources
from app.services.security.auth import require_device

logger = get_logger(__name__)

router = APIRouter(tags=["news"])

CALENDAR_RANGES = {"today", "tomorrow", "week"}


# ---------------------------------------------------------------------------
# Corps de requete
# ---------------------------------------------------------------------------

class NewsSourceRequest(BaseModel):
    """Un flux public, tel que l'utilisateur le declare."""

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=128)
    url: str = Field(min_length=8, max_length=1024)
    enabled: bool = True
    official: bool = False
    category: str | None = Field(default=None, max_length=64)
    countries: list[str] = Field(default_factory=list)
    currencies: list[str] = Field(default_factory=list)
    max_items: int = Field(default=30, ge=1, le=200, alias="maxItems")

    model_config = {"populate_by_name": True}


class NewsOptionsRequest(BaseModel):
    user_agent: str | None = Field(default=None, max_length=200, alias="userAgent")
    respect_robots: bool | None = Field(default=None, alias="respectRobots")
    timeout_seconds: float | None = Field(default=None, ge=2.0, le=60.0, alias="timeoutSeconds")
    dedup_window_hours: int | None = Field(default=None, ge=1, le=720, alias="dedupWindowHours")
    similarity_threshold: float | None = Field(
        default=None, ge=0.4, le=0.99, alias="similarityThreshold"
    )

    model_config = {"populate_by_name": True}


class NewsSourcesRequest(BaseModel):
    sources: list[NewsSourceRequest]
    options: NewsOptionsRequest | None = None


class NewsRefreshRequest(BaseModel):
    sources: list[str] | None = Field(default=None, description="Cles des flux a interroger")


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _news_payload(event: NewsEvent) -> dict[str, Any]:
    published = as_utc(event.published_at)
    received = as_utc(event.received_at)
    return {
        "id": event.id,
        "source": event.source,
        "title": event.title,
        "url": event.url,
        "publishedAt": published.isoformat() if published else None,
        "receivedAt": received.isoformat() if received else None,
        "summary": event.summary,
        "category": event.category,
        "countries": list(event.countries),
        "entities": list(event.entities),
        "affectedAssets": list(event.affected_assets),
        "affectedCurrencies": list(event.affected_currencies),
        "impactLevel": event.impact.value,
        "sentiment": event.sentiment.value,
        "confidence": event.confidence,
        "reason": event.reason,
        "verification": event.verification.value,
        "confirmations": event.confirmations,
        "duplicateOf": event.duplicate_of,
        "aiProvider": event.ai_provider_used.value if event.ai_provider_used else None,
        "aiModel": event.ai_model_used,
    }


def _economic_payload(event: EconomicEvent) -> dict[str, Any]:
    scheduled = as_utc(event.scheduled_at)
    return {
        "id": event.id,
        "externalId": event.external_id,
        "scheduledAt": scheduled.isoformat() if scheduled else None,
        "country": event.country,
        "currency": event.currency,
        "title": event.title,
        "impact": event.impact.value,
        "forecast": event.forecast,
        "previous": event.previous,
        "actual": event.actual,
        "source": event.source,
        "notifiedMinutes": list(event.notified_minutes or []),
    }


def _source_payload(source: NewsSource) -> dict[str, Any]:
    return {
        "key": source.key,
        "name": source.name,
        "url": source.url,
        "enabled": source.enabled,
        "official": source.official,
        "category": source.category,
        "countries": list(source.countries),
        "currencies": list(source.currencies),
        "maxItems": source.max_items,
    }


def _options_payload(options: NewsOptions) -> dict[str, Any]:
    return {
        "userAgent": options.user_agent,
        "respectRobots": options.respect_robots,
        "timeoutSeconds": options.timeout_seconds,
        "dedupWindowHours": options.dedup_window_hours,
        "similarityThreshold": options.similarity_threshold,
    }


def _parse_impact(raw: str | None) -> NewsImpact | None:
    if raw is None or not raw.strip():
        return None
    try:
        return NewsImpact(raw.strip().upper())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Niveau d'impact inconnu : utilisez LOW, MEDIUM, HIGH ou CRITICAL.",
        ) from exc


# ---------------------------------------------------------------------------
# Configuration des flux
# ---------------------------------------------------------------------------
# Declarees avant /news/{news_id} : sinon le chemin litteral serait capture
# par le parametre.

@router.get("/news/sources")
async def get_news_sources(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Flux configures et reglages de collecte."""
    sources = await load_sources(session)
    options = await load_options(session)
    return {
        "count": len(sources),
        "sources": [_source_payload(source) for source in sources],
        "options": _options_payload(options),
        "note": (
            "Seuls des flux publics sont interrogés. TradePilot ne contourne jamais un "
            "paywall, un CAPTCHA ni une authentification, et respecte robots.txt."
        ),
    }


@router.put("/news/sources")
async def put_news_sources(
    payload: NewsSourcesRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Remplace la liste des flux. Une entrée invalide est refusée, pas corrigée."""
    parsed: list[NewsSource] = []
    for entry in payload.sources:
        source = NewsSource.from_dict(entry.model_dump(by_alias=False))
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Source « {entry.key} » invalide : une URL http(s) est requise.",
            )
        parsed.append(source)

    saved = await store_sources(session, parsed)
    options = await load_options(session)
    if payload.options is not None:
        changes = payload.options.model_dump(by_alias=False, exclude_none=True)
        merged = options.to_dict()
        merged.update(changes)
        options = await store_options(session, NewsOptions.from_dict(merged))
    return {
        "count": len(saved),
        "sources": [_source_payload(source) for source in saved],
        "options": _options_payload(options),
    }


# ---------------------------------------------------------------------------
# Collecte
# ---------------------------------------------------------------------------

@router.post("/news/refresh")
async def refresh_news(
    payload: NewsRefreshRequest | None = None,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Lance une collecte immédiate sur les flux configurés."""
    keys = payload.sources if payload else None
    report = await news_engine.refresh(session, source_keys=keys)
    return report.to_dict()


# ---------------------------------------------------------------------------
# Consultation
# ---------------------------------------------------------------------------

@router.get("/news")
async def list_news(
    category: str | None = Query(default=None, max_length=64),
    impact: str | None = Query(default=None, max_length=16),
    symbol: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Actualités qualifiées, filtrables par catégorie, impact et instrument."""
    level = _parse_impact(impact)
    events = await news_repo.list_news(
        session,
        category=category,
        impact=level,
        symbol=symbol,
        limit=limit,
        offset=offset,
    )
    total = await news_repo.count_news(
        session, category=category, impact=level, symbol=symbol
    )
    return {
        "total": total,
        "count": len(events),
        "limit": limit,
        "offset": offset,
        "items": [_news_payload(event) for event in events],
    }


@router.get("/news/{news_id}")
async def get_news_detail(
    news_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Détail d'une actualité, avec les reprises qui la confirment."""
    event = await news_repo.get_news(session, news_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Actualité introuvable"
        )
    copies = await news_repo.duplicates_of(session, news_id) if event.id else []
    links = await news_repo.links_for(session, news_id) if event.id else []
    payload = _news_payload(event)
    payload["confirmedBy"] = [
        {
            "id": copy.id,
            "source": copy.source,
            "url": copy.url,
            "receivedAt": (as_utc(copy.received_at).isoformat() if copy.received_at else None),
        }
        for copy in copies
    ]
    payload["links"] = [
        {"symbol": link.symbol, "relevance": link.relevance} for link in links
    ]
    return payload


@router.get("/economic-calendar")
async def economic_calendar(
    range_name: str = Query(default="today", alias="range", max_length=16),
    impact: str | None = Query(default=None, max_length=16),
    currency: str | None = Query(default=None, max_length=8),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Calendrier économique : today, tomorrow ou week, filtrable."""
    window = (range_name or "today").strip().lower()
    if window not in CALENDAR_RANGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Fenêtre inconnue : utilisez today, tomorrow ou week.",
        )
    level = _parse_impact(impact)
    events, configured = await economic_calendar_engine.list_events(
        session, range_name=window, impact=level, currency=currency
    )
    start, end = economic_calendar_engine.window_for(window)
    return {
        "range": window,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "configured": configured,
        "count": len(events),
        "items": [_economic_payload(event) for event in events],
        "detail": None if configured else NO_SOURCE_MESSAGE,
    }


@router.post("/economic-calendar/refresh")
async def refresh_economic_calendar(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Synchronise le calendrier depuis les sources configurées."""
    report = await economic_calendar_engine.refresh(session)
    return report.to_dict()


__all__ = ["router"]
