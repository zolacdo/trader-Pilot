"""Assemblage de tout ce que l'on sait d'un instrument a un instant donne.

C'est l'etage « analyse deterministe » du pipeline impose par le CDC3
section 64 : donnees de marche reelles, puis mesures reproductibles, puis
contexte (actualites, calendrier). Aucune intelligence artificielle n'est
appelee ici, et aucun prix n'est invente.

Quand une information manque, le champ correspondant reste a ``None`` et le
contexte le declare : le score en tiendra compte plutot que de supposer une
valeur neutre (CDC3 section 65).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.models.intelligence import NewsImpact, NewsSentiment, Timeframe, TrendState
from app.repositories import news_repo
from app.services.market_data.engine import (
    TIMEFRAME_MINUTES,
    MarketDataEngine,
    MarketState,
    Quote,
)
from app.services.mt5.interface import Candle, SymbolInfo
from app.services.news.taxonomy import currencies_for_symbol
from app.services.technical_analysis import (
    MultiTimeframeAnalyzer,
    MultiTimeframeView,
    TechnicalAnalysis,
    profile_for,
)
from app.services.technical_analysis.multi_timeframe import TimeframeRole
from app.watcher.analysis.liquidity import LiquidityReading, read_liquidity
from app.watcher.analysis.price_action import PriceActionReading, read_price_action
from app.watcher.analysis.volatility import VolatilityReading, read_volatility
from app.watcher.analysis.volume import VolumeReading, read_volume
from app.watcher.config import WatcherConfig

logger = get_logger(__name__)

# Fenetre de lecture des actualites pour le sentiment, en heures.
SENTIMENT_WINDOW_HOURS = 12
# Fenetre de lecture pour l'analyse fondamentale, plus large : une decision de
# banque centrale porte bien au-dela de la demi-journee.
FUNDAMENTAL_WINDOW_HOURS = 72

_IMPACT_WEIGHT: dict[NewsImpact, float] = {
    NewsImpact.LOW: 1.0,
    NewsImpact.MEDIUM: 2.0,
    NewsImpact.HIGH: 3.0,
    NewsImpact.CRITICAL: 4.0,
}

_SENTIMENT_DIRECTION: dict[NewsSentiment, float] = {
    NewsSentiment.BULLISH: 1.0,
    NewsSentiment.BEARISH: -1.0,
    NewsSentiment.NEUTRAL: 0.0,
    NewsSentiment.MIXED: 0.0,
}


@dataclass(slots=True)
class DataQuality:
    """Fraicheur et suffisance des donnees (CDC3 section 66)."""

    candles: int = 0
    last_candle_at: datetime | None = None
    age_seconds: int | None = None
    fresh: bool = False
    sufficient: bool = False
    detail: str = "Aucune donnee de marche."

    @property
    def usable(self) -> bool:
        return self.fresh and self.sufficient

    def to_dict(self) -> dict[str, Any]:
        return {
            "candles": self.candles,
            "lastCandleAt": self.last_candle_at.isoformat() if self.last_candle_at else None,
            "ageSeconds": self.age_seconds,
            "fresh": self.fresh,
            "sufficient": self.sufficient,
            "usable": self.usable,
            "detail": self.detail,
        }


@dataclass(slots=True)
class SentimentReading:
    """Sentiment de marche sur l'echelle -100 / +100 (CDC3 section 18)."""

    available: bool = False
    score: float | None = None
    label: str = "UNKNOWN"
    sample: int = 0
    sources: list[str] = field(default_factory=list)
    headlines: list[str] = field(default_factory=list)
    detail: str = "Aucune actualite recente rattachee a cet instrument."

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "score": self.score,
            "label": self.label,
            "sample": self.sample,
            "sources": list(self.sources),
            "headlines": list(self.headlines),
            "detail": self.detail,
        }


@dataclass(slots=True)
class FundamentalReading:
    """Lecture fondamentale (CDC3 section 14). UNKNOWN par defaut, pas NEUTRAL."""

    available: bool = False
    direction: str = "UNKNOWN"
    importance: str = "UNKNOWN"
    notes: list[str] = field(default_factory=list)
    detail: str = "Aucun element fondamental exploitable."

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "direction": self.direction,
            "importance": self.importance,
            "notes": list(self.notes),
            "detail": self.detail,
        }


@dataclass(slots=True)
class NewsGuard:
    """Fenetre d'annonce economique en cours (CDC3 section 15)."""

    blocking: bool = False
    title: str | None = None
    currency: str | None = None
    impact: str | None = None
    scheduled_at: datetime | None = None
    minutes_to_event: float | None = None
    upcoming: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocking": self.blocking,
            "title": self.title,
            "currency": self.currency,
            "impact": self.impact,
            "scheduledAt": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "minutesToEvent": self.minutes_to_event,
            "upcoming": list(self.upcoming),
            "reason": self.reason,
        }


@dataclass(slots=True)
class MarketContext:
    """Photographie complete d'un instrument, prete a etre notee."""

    symbol: str
    broker_symbol: str
    generated_at: datetime = field(default_factory=utcnow)

    quote: Quote | None = None
    symbol_info: SymbolInfo | None = None
    market_state: MarketState | None = None

    view: MultiTimeframeView | None = None
    primary: TechnicalAnalysis | None = None
    primary_timeframe: Timeframe | None = None
    candles: list[Candle] = field(default_factory=list)

    volatility: VolatilityReading = field(default_factory=VolatilityReading)
    volume: VolumeReading = field(default_factory=VolumeReading)
    price_action: PriceActionReading = field(default_factory=PriceActionReading)
    liquidity: LiquidityReading = field(default_factory=LiquidityReading)

    quality: DataQuality = field(default_factory=DataQuality)
    sentiment: SentimentReading = field(default_factory=SentimentReading)
    fundamental: FundamentalReading = field(default_factory=FundamentalReading)
    news_guard: NewsGuard = field(default_factory=NewsGuard)

    @property
    def price(self) -> float | None:
        """Prix de reference : milieu de fourchette, sinon derniere cloture."""
        if self.quote is not None and self.quote.mid is not None:
            return self.quote.mid
        if self.primary is not None:
            return self.primary.last_close
        return None

    @property
    def bias(self) -> TrendState:
        return self.view.bias if self.view is not None else TrendState.NEUTRAL

    @property
    def spread_points(self) -> int | None:
        return self.quote.spread_points if self.quote is not None else None

    @property
    def market_open(self) -> bool | None:
        """``None`` quand l'etat du marche n'a pas pu etre determine."""
        if self.market_state is None or self.market_state.status == "UNKNOWN":
            return None
        return self.market_state.status == "OPEN"

    @property
    def usable(self) -> bool:
        """Le contexte permet-il seulement d'envisager une analyse ?"""
        return (
            self.primary is not None
            and self.primary.usable
            and self.quality.usable
            and self.price is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "brokerSymbol": self.broker_symbol,
            "generatedAt": self.generated_at.isoformat(),
            "price": self.price,
            "quote": self.quote.to_dict() if self.quote else None,
            "marketState": self.market_state.to_dict() if self.market_state else None,
            "bias": self.bias.value,
            "primaryTimeframe": self.primary_timeframe.value if self.primary_timeframe else None,
            "multiTimeframe": self.view.to_dict() if self.view else None,
            "technical": self.primary.to_dict() if self.primary else None,
            "volatility": self.volatility.to_dict(),
            "volume": self.volume.to_dict(),
            "priceAction": self.price_action.to_dict(),
            "liquidity": self.liquidity.to_dict(),
            "quality": self.quality.to_dict(),
            "sentiment": self.sentiment.to_dict(),
            "fundamental": self.fundamental.to_dict(),
            "newsGuard": self.news_guard.to_dict(),
        }

    def summary(self) -> dict[str, Any]:
        """Vue compacte, suffisante pour l'API et pour le prompt IA."""
        return {
            "symbol": self.symbol,
            "price": self.price,
            "bias": self.bias.value,
            "timeframes": self.view.states() if self.view else {},
            # L'etat dependant du role masque la tendance : une H1 baissiere en
            # repli s'enregistrait en ``PULLBACK``. Sur les 41 premiers signaux
            # denoues, 15 avaient ainsi leur tendance H1 perdue, et plus aucune
            # requete ne pouvait mesurer l'accord des unites de temps.
            "trends": self.view.trends() if self.view else {},
            "volatility": self.volatility.level.value,
            "volume": self.volume.detail,
            "priceAction": self.price_action.detail,
            "liquidity": self.liquidity.detail,
            "sentiment": self.sentiment.label,
            "fundamental": self.fundamental.direction,
            "spreadPoints": self.spread_points,
            "marketOpen": self.market_open,
        }


_analyzer = MultiTimeframeAnalyzer()


async def build_context(
    session: AsyncSession,
    engine: MarketDataEngine,
    symbol: str,
    broker_symbol: str,
    config: WatcherConfig,
    now: datetime | None = None,
) -> MarketContext:
    """Construit le contexte complet d'un instrument.

    Ne leve jamais : un contexte partiel est toujours preferable a une panne,
    et ce qui manque est declare (CDC3 section 55).
    """
    moment = now or utcnow()
    context = MarketContext(symbol=symbol, broker_symbol=broker_symbol, generated_at=moment)
    profile = profile_for(config.profile)

    try:
        context.view = await _analyzer.analyse(engine, broker_symbol, profile, bars=config.bars)
    except Exception as exc:
        logger.warning("Analyse multi-timeframe impossible sur %s : %s", symbol, exc)
        context.quality.detail = f"Analyse multi-timeframe indisponible : {exc}"
        return context

    context.primary_timeframe = _primary_timeframe(profile, context.view)
    if context.primary_timeframe is not None:
        context.primary = context.view.analysis_for(context.primary_timeframe)
        context.candles = await engine.candles(
            broker_symbol, context.primary_timeframe, config.bars
        )

    context.quality = _read_quality(
        context.candles, config, moment, context.primary_timeframe
    )

    if context.candles and context.primary is not None:
        context.volatility = read_volatility(context.candles)
        context.volume = read_volume(context.candles, context.primary.breakout)
        context.price_action = read_price_action(context.candles)
        context.liquidity = read_liquidity(
            context.candles, context.primary.swings, context.primary.atr
        )

    try:
        context.quote = await engine.quote(broker_symbol)
        context.symbol_info = await engine.symbol_info(broker_symbol)
        context.market_state = await engine.market_state(broker_symbol)
    except Exception as exc:
        logger.debug("Cotation %s indisponible : %s", symbol, exc)

    currencies = currencies_for_symbol(symbol)
    context.sentiment = await _read_sentiment(session, symbol, currencies, moment)
    context.fundamental = await _read_fundamental(session, symbol, currencies, moment)
    context.news_guard = await _read_news_guard(session, currencies, config, moment)
    return context


def _primary_timeframe(profile: Any, view: MultiTimeframeView) -> Timeframe | None:
    """Unite de temps de declenchement, sinon la plus basse reellement analysee.

    Le CDC3 section 6 interdit d'analyser M1 isolement : on garde donc celle
    que le profil designe comme declencheur, pas la plus rapide disponible.
    """
    for role in (TimeframeRole.TRIGGER, TimeframeRole.CONFIRMATION, TimeframeRole.STRUCTURE):
        for frame in profile.of_role(role):
            analysis = view.analysis_for(frame)
            if analysis is not None and analysis.usable:
                return frame
    for verdict in view.verdicts:
        if verdict.analysis is not None and verdict.analysis.usable:
            return verdict.timeframe
    return None


def freshness_tolerance(config: WatcherConfig, timeframe: Timeframe | None) -> int:
    """Age maximal acceptable de la derniere bougie, en secondes.

    Le seuil DOIT dependre de l'unite de temps analysee. Une bougie M15 a
    naturellement jusqu'a quinze minutes quand elle vient de s'ouvrir : un
    plafond fixe de dix minutes declarerait « donnees trop anciennes » en
    permanence et aucun signal ne sortirait jamais.

    On retient donc deux bougies de tolerance, avec le reglage
    ``max_data_age_seconds`` comme plancher — il reste utile pour les unites de
    temps tres courtes.
    """
    minutes = TIMEFRAME_MINUTES.get(timeframe) if timeframe is not None else None
    if minutes is None:
        return int(config.max_data_age_seconds)
    return max(int(config.max_data_age_seconds), minutes * 60 * 2)


def _read_quality(
    candles: list[Candle],
    config: WatcherConfig,
    now: datetime,
    timeframe: Timeframe | None = None,
) -> DataQuality:
    """Mesure la fraicheur et la profondeur reelles des donnees."""
    quality = DataQuality(candles=len(candles))
    if not candles:
        return quality
    last = candles[-1].time
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    age = int((now - last).total_seconds())
    tolerance = freshness_tolerance(config, timeframe)
    quality.last_candle_at = last
    quality.age_seconds = max(0, age)
    quality.sufficient = len(candles) >= config.minimum_candles
    quality.fresh = quality.age_seconds <= tolerance

    if not quality.sufficient:
        quality.detail = (
            f"{len(candles)} bougie(s) disponibles, {config.minimum_candles} requises."
        )
    elif not quality.fresh:
        quality.detail = (
            f"Derniere bougie il y a {quality.age_seconds // 60} minute(s), "
            f"au-dela des {tolerance // 60} minute(s) tolerees sur "
            f"{timeframe.value if timeframe else 'cette unite de temps'}."
        )
    else:
        quality.detail = f"{len(candles)} bougies, derniere il y a {quality.age_seconds} s."
    return quality


def _relevant(event: Any, symbol: str, currencies: set[str]) -> bool:
    """L'actualite concerne-t-elle reellement cet instrument ?"""
    assets = {str(item).upper() for item in (event.affected_assets or [])}
    if symbol.upper() in assets:
        return True
    linked = {str(item).upper() for item in (event.affected_currencies or [])}
    return bool(linked & {code.upper() for code in currencies})


async def _read_sentiment(
    session: AsyncSession, symbol: str, currencies: set[str], now: datetime
) -> SentimentReading:
    """Sentiment issu des actualites deja collectees par le Bridge.

    Le watcher ne collecte pas lui-meme : le moteur d'actualites du Bridge
    remplit ces tables en continu. Dupliquer la collecte doublerait les
    requetes reseau pour un resultat identique.
    """
    reading = SentimentReading()
    try:
        events = await news_repo.recent_news(
            session, now - timedelta(hours=SENTIMENT_WINDOW_HOURS)
        )
    except Exception as exc:
        logger.debug("Actualites indisponibles pour %s : %s", symbol, exc)
        reading.detail = "Base d'actualites momentanement illisible."
        return reading

    related = [event for event in events if _relevant(event, symbol, currencies)]
    if not related:
        return reading

    total_weight = 0.0
    weighted = 0.0
    for event in related:
        weight = _IMPACT_WEIGHT.get(event.impact, 1.0) * max(0.2, float(event.confidence or 0.5))
        direction = _SENTIMENT_DIRECTION.get(event.sentiment, 0.0)
        total_weight += weight
        weighted += direction * weight

    if total_weight <= 0:
        return reading

    score = max(-100.0, min(100.0, weighted / total_weight * 100.0))
    reading.available = True
    reading.score = round(score, 1)
    reading.sample = len(related)
    reading.sources = sorted({event.source for event in related})[:5]
    reading.headlines = [event.title for event in related[:3]]
    if score >= 20:
        reading.label = "BULLISH"
    elif score <= -20:
        reading.label = "BEARISH"
    else:
        reading.label = "NEUTRAL"
    reading.detail = (
        f"{len(related)} actualite(s) rattachee(s) sur {SENTIMENT_WINDOW_HOURS} h, "
        f"score {reading.score:+.0f}."
    )
    return reading


async def _read_fundamental(
    session: AsyncSession, symbol: str, currencies: set[str], now: datetime
) -> FundamentalReading:
    """Lecture fondamentale a partir des seules actualites a fort impact."""
    reading = FundamentalReading()
    try:
        events = await news_repo.recent_news(
            session, now - timedelta(hours=FUNDAMENTAL_WINDOW_HOURS)
        )
    except Exception as exc:
        logger.debug("Actualites fondamentales indisponibles pour %s : %s", symbol, exc)
        return reading

    strong = [
        event
        for event in events
        if event.impact in (NewsImpact.HIGH, NewsImpact.CRITICAL)
        and _relevant(event, symbol, currencies)
    ]
    if not strong:
        return reading

    balance = sum(_SENTIMENT_DIRECTION.get(event.sentiment, 0.0) for event in strong)
    reading.available = True
    reading.importance = (
        NewsImpact.CRITICAL.value
        if any(event.impact is NewsImpact.CRITICAL for event in strong)
        else NewsImpact.HIGH.value
    )
    if balance > 0:
        reading.direction = "BULLISH"
    elif balance < 0:
        reading.direction = "BEARISH"
    else:
        reading.direction = "NEUTRAL"
    reading.notes = [event.title for event in strong[:3]]
    reading.detail = (
        f"{len(strong)} actualite(s) a fort impact sur {FUNDAMENTAL_WINDOW_HOURS} h, "
        f"orientation {reading.direction}."
    )
    return reading


async def _read_news_guard(
    session: AsyncSession, currencies: set[str], config: WatcherConfig, now: datetime
) -> NewsGuard:
    """Verifie si une annonce economique majeure encadre l'instant present."""
    guard = NewsGuard()
    if not currencies:
        return guard

    horizon = max(config.before_news_minutes, config.critical_news_minutes)
    try:
        events = await news_repo.list_economic_events(
            session,
            start=now - timedelta(minutes=max(config.after_news_minutes, horizon)),
            end=now + timedelta(minutes=horizon * 4),
        )
    except Exception as exc:
        logger.debug("Calendrier economique indisponible : %s", exc)
        return guard

    upper = {code.upper() for code in currencies}
    relevant = [
        event
        for event in events
        if (event.currency or "").upper() in upper
        and event.impact in (NewsImpact.HIGH, NewsImpact.CRITICAL)
    ]
    guard.upcoming = [
        {
            "title": event.title,
            "currency": event.currency,
            "impact": event.impact.value,
            "scheduledAt": (as_utc(event.scheduled_at) or event.scheduled_at).isoformat(),
        }
        for event in relevant
        if (as_utc(event.scheduled_at) or event.scheduled_at) >= now
    ][:5]

    if not config.block_high_impact_news:
        return guard

    for event in relevant:
        scheduled = as_utc(event.scheduled_at)
        if scheduled is None:
            continue
        delta_minutes = (scheduled - now).total_seconds() / 60.0
        before = (
            config.critical_news_minutes
            if event.impact is NewsImpact.CRITICAL
            else config.before_news_minutes
        )
        after = (
            config.critical_news_minutes
            if event.impact is NewsImpact.CRITICAL
            else config.after_news_minutes
        )
        if -after <= delta_minutes <= before:
            guard.blocking = True
            guard.title = event.title
            guard.currency = event.currency
            guard.impact = event.impact.value
            guard.scheduled_at = scheduled
            guard.minutes_to_event = round(delta_minutes, 1)
            moment = (
                f"dans {abs(round(delta_minutes))} minute(s)"
                if delta_minutes >= 0
                else f"il y a {abs(round(delta_minutes))} minute(s)"
            )
            guard.reason = (
                f"Annonce {event.impact.value} sur {event.currency} ({event.title}) {moment}."
            )
            break
    return guard


__all__ = [
    "DataQuality",
    "FundamentalReading",
    "MarketContext",
    "NewsGuard",
    "SentimentReading",
    "build_context",
]
