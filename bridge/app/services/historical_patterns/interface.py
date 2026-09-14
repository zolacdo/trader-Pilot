"""Contrat minimal attendu du moteur de donnees de marche (CDC2 section 22).

Le moteur de donnees lui-meme est construit ailleurs. Ce module ne definit que
ce dont l'analyse historique a besoin : une fonction capable de rendre des
bougies pour un symbole, une unite de temps et une periode. Toute source
respectant ``CandleProvider`` convient, y compris ``MetaTraderService``.

``MarketHistory`` est la seule porte d'acces aux bougies pendant l'analyse :
``upto()`` ne rend jamais une bougie posterieure a l'instant demande, et
``future()`` porte un nom explicite car il est reserve au calcul du RESULTAT
d'une configuration passee, jamais a la construction de ses caracteristiques.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from app.services.mt5.interface import Candle

# Duree d'une bougie, en secondes. Sert a convertir un horizon en nombre de bougies.
TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
    "W1": 604800,
    "MN1": 2592000,
}


class LookAheadError(RuntimeError):
    """Une lecture de donnee future a ete tentee hors du calcul de resultat."""


@runtime_checkable
class CandleProvider(Protocol):
    """Interface attendue du moteur de donnees de marche.

    La signature reprend exactement celle de ``MetaTraderService.candles`` :
    l'integration se fera par simple injection, sans adaptateur.
    """

    async def candles(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:  # pragma: no cover - contrat
        ...


def as_utc(moment: datetime) -> datetime:
    """Date toujours comparable : une date naive est consideree UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def timeframe_seconds(timeframe: str) -> int | None:
    return TIMEFRAME_SECONDS.get(timeframe.upper())


def bars_for_hours(timeframe: str, hours: float) -> int | None:
    """Nombre de bougies couvrant un horizon, ou None si l'unite est inconnue."""
    seconds = timeframe_seconds(timeframe)
    if seconds is None or seconds <= 0 or hours <= 0:
        return None
    return max(1, round(hours * 3600 / seconds))


@dataclass(slots=True)
class MarketHistory:
    """Series de bougies d'un instrument, triees et bornees par instant.

    Aucune methode ne rend de bougie posterieure a l'instant demande, sauf
    ``future()`` qui est explicitement reserve a l'evaluation des resultats.
    """

    symbol: str
    series: dict[str, list[Candle]] = field(default_factory=dict)
    _times: dict[str, list[datetime]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        normalised: dict[str, list[Candle]] = {}
        for timeframe, candles in self.series.items():
            ordered = sorted(candles, key=lambda candle: as_utc(candle.time))
            key = timeframe.upper()
            normalised[key] = ordered
            self._times[key] = [as_utc(candle.time) for candle in ordered]
        self.series = normalised

    # -- lecture causale -------------------------------------------------

    def timeframes(self) -> list[str]:
        return sorted(self.series)

    def has(self, timeframe: str) -> bool:
        return bool(self.series.get(timeframe.upper()))

    def count(self, timeframe: str) -> int:
        return len(self.series.get(timeframe.upper(), ()))

    def upto(self, timeframe: str, moment: datetime) -> list[Candle]:
        """Bougies dont l'horodatage est <= moment. Jamais au-dela."""
        key = timeframe.upper()
        candles = self.series.get(key)
        if not candles:
            return []
        cut = bisect_right(self._times[key], as_utc(moment))
        return candles[:cut]

    def index_at(self, timeframe: str, moment: datetime) -> int | None:
        """Position de la derniere bougie <= moment, ou None."""
        key = timeframe.upper()
        if not self.series.get(key):
            return None
        cut = bisect_right(self._times[key], as_utc(moment))
        return cut - 1 if cut > 0 else None

    def moments(
        self,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[datetime]:
        """Horodatages disponibles, eventuellement bornes."""
        key = timeframe.upper()
        times = self._times.get(key, [])
        lower = as_utc(start) if start is not None else None
        upper = as_utc(end) if end is not None else None
        return [
            moment
            for moment in times
            if (lower is None or moment >= lower) and (upper is None or moment <= upper)
        ]

    def span(self, timeframe: str) -> tuple[datetime, datetime] | None:
        times = self._times.get(timeframe.upper())
        if not times:
            return None
        return times[0], times[-1]

    # -- lecture du futur, reservee au calcul des resultats ---------------

    def future(self, timeframe: str, moment: datetime, until: datetime | None = None) -> list[Candle]:
        """Bougies strictement posterieures a moment.

        Usage unique : mesurer ce qui s'est REELLEMENT passe apres une
        configuration passee. Interdit dans la construction des features.
        """
        key = timeframe.upper()
        candles = self.series.get(key)
        if not candles:
            return []
        start = bisect_right(self._times[key], as_utc(moment))
        if until is None:
            return candles[start:]
        stop = bisect_right(self._times[key], as_utc(until))
        return candles[start:stop]


@dataclass(slots=True)
class StaticCandleProvider:
    """Source de bougies en memoire : tests, rejeu, analyse hors ligne."""

    data: dict[tuple[str, str], list[Candle]] = field(default_factory=dict)

    def add(self, symbol: str, timeframe: str, candles: Iterable[Candle]) -> None:
        key = (symbol, timeframe.upper())
        ordered = sorted(candles, key=lambda candle: as_utc(candle.time))
        self.data[key] = ordered

    async def candles(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:
        low, high = as_utc(start), as_utc(end)
        return [
            candle
            for candle in self.data.get((symbol, timeframe.upper()), [])
            if low <= as_utc(candle.time) <= high
        ]


async def load_history(
    provider: CandleProvider,
    symbol: str,
    timeframes: Sequence[str],
    start: datetime,
    end: datetime,
) -> MarketHistory:
    """Charge plusieurs unites de temps via la source injectee."""
    series: dict[str, list[Candle]] = {}
    for timeframe in timeframes:
        candles = await provider.candles(symbol, timeframe.upper(), start, end)
        if candles:
            series[timeframe.upper()] = list(candles)
    return MarketHistory(symbol=symbol, series=series)


def horizon_end(moment: datetime, hours: float) -> datetime:
    return as_utc(moment) + timedelta(hours=hours)


__all__ = [
    "TIMEFRAME_SECONDS",
    "CandleProvider",
    "LookAheadError",
    "MarketHistory",
    "StaticCandleProvider",
    "as_utc",
    "bars_for_hours",
    "horizon_end",
    "load_history",
    "timeframe_seconds",
]
