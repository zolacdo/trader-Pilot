"""Cache memoire des series de bougies.

Telecharger des millions de bougies a chaque analyse serait inutile et lent
(CDC2 section 16). Les series sont donc conservees en memoire, avec une duree
de vie proportionnelle a la taille de la bougie : une serie M1 se perime en
quelques dizaines de secondes, une serie D1 tient plusieurs minutes.

Le cache ne contient QUE ce que le broker a reellement renvoye. Il ne comble
jamais un trou et n'extrapole aucune bougie.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass

from app.services.mt5.interface import Candle

# Bornes de la duree de vie d'une entree, en secondes.
MIN_TTL_SECONDS = 10.0
MAX_TTL_SECONDS = 600.0

# Une entree vit environ la moitie de la duree d'une bougie.
TTL_RATIO = 30.0


def ttl_for(timeframe_minutes: int) -> float:
    """Duree de vie d'une serie, bornee entre 10 secondes et 10 minutes."""
    if timeframe_minutes <= 0:
        return MIN_TTL_SECONDS
    return max(MIN_TTL_SECONDS, min(timeframe_minutes * TTL_RATIO, MAX_TTL_SECONDS))


@dataclass(slots=True)
class CacheEntry:
    """Serie memorisee et l'instant ou elle a ete recuperee."""

    candles: list[Candle]
    stored_at: float

    @property
    def size(self) -> int:
        return len(self.candles)


class CandleCache:
    """Cache LRU borne, sans dependance a une horloge externe reelle.

    ``clock`` est injectable pour que les tests puissent faire vieillir une
    entree sans attendre.
    """

    def __init__(self, max_entries: int = 256, clock=time.monotonic) -> None:
        self._entries: OrderedDict[tuple[str, str], CacheEntry] = OrderedDict()
        self._max_entries = max(8, int(max_entries))
        self._clock = clock
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, symbol: str, timeframe: str, ttl: float, minimum: int = 1) -> list[Candle] | None:
        """Serie encore valide, ou None si absente, perimee ou trop courte."""
        key = (symbol, timeframe)
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        if self._clock() - entry.stored_at > ttl:
            self._entries.pop(key, None)
            self.misses += 1
            return None
        if entry.size < minimum:
            # La serie memorisee est plus courte que ce qui est demande :
            # mieux vaut redemander au broker que de rendre une serie tronquee.
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return list(entry.candles)

    def put(self, symbol: str, timeframe: str, candles: list[Candle]) -> None:
        key = (symbol, timeframe)
        self._entries[key] = CacheEntry(candles=list(candles), stored_at=self._clock())
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def invalidate(self, symbol: str | None = None) -> int:
        """Oublie une serie, toutes celles d'un symbole, ou tout le cache."""
        if symbol is None:
            removed = len(self._entries)
            self._entries.clear()
            return removed
        keys = [key for key in self._entries if key[0] == symbol]
        for key in keys:
            self._entries.pop(key, None)
        return len(keys)

    def stats(self) -> dict[str, int | float]:
        total = self.hits + self.misses
        return {
            "entries": len(self._entries),
            "maxEntries": self._max_entries,
            "hits": self.hits,
            "misses": self.misses,
            "hitRatio": round(self.hits / total, 3) if total else 0.0,
        }


__all__ = ["MAX_TTL_SECONDS", "MIN_TTL_SECONDS", "CacheEntry", "CandleCache", "ttl_for"]
