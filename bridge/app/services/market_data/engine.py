"""Moteur de donnees de marche (CDC2 section 16).

MetaTrader 5 est la source prioritaire : le moteur accepte n'importe quelle
implementation de ``MetaTraderService`` (terminal reel ou simulateur) et ne
fabrique jamais de donnee. Quand le broker ne repond pas, le moteur rend ce
qu'il a deja en cache, sinon une serie vide et un etat explicite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.config.logging_config import get_logger
from app.models.intelligence import Timeframe
from app.services.market_data.cache import CandleCache, ttl_for
from app.services.mt5.interface import Candle, MetaTraderService, SymbolInfo, Tick
from app.services.technical_analysis import indicators

logger = get_logger(__name__)

# Duree d'une bougie, en minutes. MN1 est declare pour l'avenir : il n'est
# fourni que si le terminal l'accepte, sinon la serie revient vide.
TIMEFRAME_MINUTES: dict[Timeframe, int] = {
    Timeframe.M1: 1,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.M30: 30,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
    Timeframe.W1: 10080,
    Timeframe.MN1: 43200,
}

# Timeframes garantis par le CDC2. MN1 reste optionnel.
SUPPORTED_TIMEFRAMES: tuple[Timeframe, ...] = (
    Timeframe.M1,
    Timeframe.M5,
    Timeframe.M15,
    Timeframe.M30,
    Timeframe.H1,
    Timeframe.H4,
    Timeframe.D1,
    Timeframe.W1,
)

DEFAULT_BARS = 300
MAX_BARS = 1500
MIN_BARS = 5

# Duree de vie des metadonnees et de la liste des symboles, en secondes.
METADATA_TTL = 120.0
SYMBOLS_TTL = 300.0

# Au-dela, la derniere bougie M1 est trop ancienne pour parler d'un marche ouvert.
OPEN_MARKET_SECONDS = 180


def parse_timeframe(value: str | Timeframe | None) -> Timeframe | None:
    """Convertit une etiquette en ``Timeframe``, sans lever d'exception."""
    if value is None:
        return None
    if isinstance(value, Timeframe):
        return value
    try:
        return Timeframe(str(value).strip().upper())
    except ValueError:
        return None


@dataclass(slots=True)
class Quote:
    """Cotation instantanee. Chaque champ absent reste a ``None``."""

    symbol: str
    bid: float | None = None
    ask: float | None = None
    spread_points: int | None = None
    spread_price: float | None = None
    time: datetime | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "spreadPoints": self.spread_points,
            "spreadPrice": self.spread_price,
            "time": self.time.isoformat() if self.time else None,
        }


@dataclass(slots=True)
class MarketState:
    """Etat observe d'un instrument : ouvert, ferme, ou indetermine."""

    symbol: str
    status: str = "UNKNOWN"
    tradable: bool | None = None
    quote: Quote | None = None
    last_candle_at: datetime | None = None
    seconds_since_last_candle: int | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "tradable": self.tradable,
            "quote": self.quote.to_dict() if self.quote else None,
            "lastCandleAt": self.last_candle_at.isoformat() if self.last_candle_at else None,
            "secondsSinceLastCandle": self.seconds_since_last_candle,
            "detail": self.detail,
        }


class MarketDataEngine:
    """Acces unique aux bougies, cotations et metadonnees d'un service MT5.

    Le moteur travaille avec le nom de symbole **du broker**. La resolution du
    nom canonique (XAUUSD -> XAUUSDm) est faite en amont par le SymbolResolver.
    """

    def __init__(
        self,
        service: MetaTraderService,
        max_cache_entries: int = 256,
        clock=None,
    ) -> None:
        self._service = service
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._candles = CandleCache(max_entries=max_cache_entries)
        self._metadata: dict[str, tuple[float, SymbolInfo | None]] = {}
        self._symbols: tuple[float, list[str]] | None = None
        self.errors = 0
        self.last_error: str | None = None

    @property
    def service(self) -> MetaTraderService:
        return self._service

    def now(self) -> datetime:
        return self._clock()

    # ------------------------------------------------------------------
    # Bougies
    # ------------------------------------------------------------------
    async def candles(
        self,
        symbol: str,
        timeframe: str | Timeframe,
        bars: int = DEFAULT_BARS,
        refresh: bool = False,
    ) -> list[Candle]:
        """Dernieres ``bars`` bougies cloturees ou en cours, cache compris."""
        frame = parse_timeframe(timeframe)
        if frame is None or not symbol:
            return []
        minutes = TIMEFRAME_MINUTES.get(frame)
        if minutes is None:
            return []
        wanted = max(MIN_BARS, min(int(bars), MAX_BARS))

        if not refresh:
            cached = self._candles.get(symbol, frame.value, ttl_for(minutes), minimum=wanted)
            if cached is not None:
                return cached[-wanted:]

        try:
            # On demande « les N dernieres bougies » plutot qu'une plage de
            # dates : une plage oblige le terminal a rapatrier l'historique
            # manquant, ce qui peut le bloquer assez longtemps pour que le
            # chien de garde tue le processus MetaTrader.
            fetched = await self._service.recent_candles(symbol, frame.value, wanted + 5)
        except Exception as exc:  # le terminal peut disparaitre a tout moment
            self.errors += 1
            self.last_error = str(exc)
            logger.warning("Bougies %s %s indisponibles : %s", symbol, frame.value, exc)
            stale = self._candles.get(symbol, frame.value, ttl_for(minutes) * 10, minimum=MIN_BARS)
            return stale[-wanted:] if stale else []

        if not fetched:
            return []
        series = sorted(fetched, key=lambda candle: candle.time)[-MAX_BARS:]
        self._candles.put(symbol, frame.value, series)
        return series[-wanted:]

    async def series(
        self,
        symbol: str,
        timeframes: list[Timeframe] | tuple[Timeframe, ...],
        bars: int = DEFAULT_BARS,
    ) -> dict[Timeframe, list[Candle]]:
        """Plusieurs timeframes d'un coup, chacun servi par le cache."""
        result: dict[Timeframe, list[Candle]] = {}
        for frame in timeframes:
            result[frame] = await self.candles(symbol, frame, bars)
        return result

    async def atr(
        self, symbol: str, timeframe: str | Timeframe, period: int = 14, bars: int | None = None
    ) -> float | None:
        """ATR sur le timeframe demande, ``None`` si l'historique manque."""
        needed = bars if bars is not None else max(period * 4, 60)
        candles = await self.candles(symbol, timeframe, needed)
        return indicators.atr(candles, period)

    # ------------------------------------------------------------------
    # Cotations et metadonnees
    # ------------------------------------------------------------------
    async def tick(self, symbol: str) -> Tick | None:
        try:
            return await self._service.symbol_tick(symbol)
        except Exception as exc:
            self.errors += 1
            self.last_error = str(exc)
            logger.debug("Tick %s indisponible : %s", symbol, exc)
            return None

    async def symbol_info(self, symbol: str, refresh: bool = False) -> SymbolInfo | None:
        """Metadonnees du symbole, memorisees quelques minutes."""
        cached = self._metadata.get(symbol)
        stamp = self.now().timestamp()
        if not refresh and cached is not None and stamp - cached[0] <= METADATA_TTL:
            return cached[1]
        try:
            info = await self._service.symbol_info(symbol)
        except Exception as exc:
            self.errors += 1
            self.last_error = str(exc)
            logger.debug("Metadonnees %s indisponibles : %s", symbol, exc)
            return cached[1] if cached else None
        self._metadata[symbol] = (stamp, info)
        return info

    async def quote(self, symbol: str) -> Quote | None:
        """Cotation courante. ``None`` si le broker ne cote pas ce symbole."""
        tick = await self.tick(symbol)
        if tick is None:
            return None
        info = await self.symbol_info(symbol)
        spread_price = tick.spread if tick.bid and tick.ask else None
        points: int | None = None
        if info is not None and info.point > 0 and spread_price is not None:
            points = tick.spread_points(info.point)
        elif info is not None and info.spread > 0:
            points = info.spread
        return Quote(
            symbol=symbol,
            bid=tick.bid or None,
            ask=tick.ask or None,
            spread_points=points,
            spread_price=spread_price,
            time=tick.time,
        )

    async def available_symbols(self, refresh: bool = False) -> list[str]:
        """Liste reelle des symboles du compte. Jamais une liste supposee."""
        stamp = self.now().timestamp()
        if not refresh and self._symbols is not None and stamp - self._symbols[0] <= SYMBOLS_TTL:
            return list(self._symbols[1])
        try:
            names = await self._service.symbols()
        except Exception as exc:
            self.errors += 1
            self.last_error = str(exc)
            logger.warning("Liste des symboles indisponible : %s", exc)
            return list(self._symbols[1]) if self._symbols else []
        ordered = sorted(names)
        self._symbols = (stamp, ordered)
        return list(ordered)

    async def is_available(self, symbol: str) -> bool:
        """Presence confirmee du symbole chez le broker."""
        return await self.symbol_info(symbol) is not None

    async def market_state(self, symbol: str) -> MarketState:
        """Etat du marche deduit de la derniere bougie M1 et de la cotation."""
        info = await self.symbol_info(symbol)
        if info is None:
            return MarketState(
                symbol=symbol,
                status="UNKNOWN",
                detail="Symbole inconnu du broker : aucune donnée de marché disponible.",
            )
        quote = await self.quote(symbol)
        candles = await self.candles(symbol, Timeframe.M1, MIN_BARS)
        state = MarketState(symbol=symbol, tradable=info.tradable, quote=quote)
        if not candles:
            state.status = "UNKNOWN"
            state.detail = "Aucune bougie M1 récente : état du marché indéterminé."
            return state
        last = candles[-1]
        last_time = last.time if last.time.tzinfo else last.time.replace(tzinfo=UTC)
        age = int((self.now() - last_time).total_seconds())
        state.last_candle_at = last_time
        state.seconds_since_last_candle = max(0, age)
        if age <= OPEN_MARKET_SECONDS:
            state.status = "OPEN"
            state.detail = "Cotations en cours."
        else:
            state.status = "CLOSED"
            state.detail = f"Dernière bougie M1 il y a {max(0, age) // 60} minute(s)."
        return state

    # ------------------------------------------------------------------
    # Entretien
    # ------------------------------------------------------------------
    def invalidate(self, symbol: str | None = None) -> None:
        """Oublie les series memorisees (changement de compte, de broker...)."""
        self._candles.invalidate(symbol)
        if symbol is None:
            self._metadata.clear()
            self._symbols = None
        else:
            self._metadata.pop(symbol, None)

    def stats(self) -> dict[str, Any]:
        return {
            "service": getattr(self._service, "name", "metatrader"),
            "candleCache": self._candles.stats(),
            "metadataEntries": len(self._metadata),
            "symbolsCached": len(self._symbols[1]) if self._symbols else 0,
            "errors": self.errors,
            "lastError": self.last_error,
        }


__all__ = [
    "DEFAULT_BARS",
    "MAX_BARS",
    "SUPPORTED_TIMEFRAMES",
    "TIMEFRAME_MINUTES",
    "MarketDataEngine",
    "MarketState",
    "Quote",
    "parse_timeframe",
]
