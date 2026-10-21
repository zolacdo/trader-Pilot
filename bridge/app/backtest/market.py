"""Le marche tel qu'il etait a un instant passe, et rien au-dela.

Le moteur live lit les bougies « cloturees ou en cours » : la derniere bougie
de chaque unite de temps est donc en formation. Le rejeu la reconstruit a
partir des bougies M5 deja closes au curseur, pour montrer au watcher ce qu'il
aurait vu a cet instant. Utiliser la bougie H4 complete du fichier lui ferait
lire jusqu'a quatre heures de futur.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from app.models.intelligence import Timeframe
from app.services.market_data.engine import TIMEFRAME_MINUTES, MarketState, Quote
from app.services.mt5.interface import Candle, SymbolInfo


class HistoricalMarket:
    """Meme interface de lecture que ``MarketDataEngine``, bornee par ``cursor``."""

    def __init__(
        self,
        symbol: str,
        frames: dict[Timeframe, dict[str, np.ndarray]],
        info: SymbolInfo,
        base: Timeframe = Timeframe.M5,
    ) -> None:
        if base not in frames:
            raise ValueError(f"L'unite de base {base.value} est indispensable au rejeu.")
        self.symbol = symbol
        self.frames = frames
        self.info = info
        self.base = base
        self.base_seconds = TIMEFRAME_MINUTES[base] * 60
        # Instant de la decision, secondes epoch : toute bougie qui finit
        # apres lui est invisible.
        self.cursor = 0

    def moment(self) -> datetime:
        return datetime.fromtimestamp(self.cursor, UTC)

    async def candles(self, symbol: str, frame: Timeframe | str, bars: int = 300) -> list[Candle]:
        frame = Timeframe(frame) if not isinstance(frame, Timeframe) else frame
        rates = self.frames.get(frame)
        if rates is None:
            return []
        seconds = TIMEFRAME_MINUTES[frame] * 60
        times = rates["time"]
        closed = int(np.searchsorted(times, self.cursor - seconds, side="right"))
        candles = [_candle(rates, i) for i in range(max(0, closed - bars), closed)]
        if frame is not self.base and closed < len(times) and times[closed] < self.cursor:
            forming = self._forming(int(times[closed]))
            if forming is not None:
                candles.append(forming)
                candles = candles[-bars:]
        return candles

    def _forming(self, start: int) -> Candle | None:
        """Bougie en cours, agregee des bougies de base closes depuis ``start``."""
        base = self.frames[self.base]
        times = base["time"]
        lo = int(np.searchsorted(times, start, side="left"))
        hi = int(np.searchsorted(times, self.cursor - self.base_seconds, side="right"))
        if hi <= lo:
            return None
        return Candle(
            time=datetime.fromtimestamp(start, UTC),
            open=float(base["open"][lo]),
            high=float(base["high"][lo:hi].max()),
            low=float(base["low"][lo:hi].min()),
            close=float(base["close"][hi - 1]),
            tick_volume=int(base["tick_volume"][lo:hi].sum()),
        )

    def last_base_index(self) -> int:
        """Indice de la derniere bougie de base close au curseur, -1 si aucune."""
        times = self.frames[self.base]["time"]
        return int(np.searchsorted(times, self.cursor - self.base_seconds, side="right")) - 1

    async def quote(self, symbol: str) -> Quote | None:
        index = self.last_base_index()
        if index < 0:
            return None
        base = self.frames[self.base]
        bid = float(base["close"][index])
        spread_points = int(base["spread"][index])
        spread_price = spread_points * self.info.point
        return Quote(
            symbol=symbol,
            bid=bid,
            ask=bid + spread_price,
            spread_points=spread_points,
            spread_price=spread_price,
            time=self.moment(),
        )

    async def symbol_info(self, symbol: str, refresh: bool = False) -> SymbolInfo | None:
        return self.info

    async def market_state(self, symbol: str) -> MarketState:
        # Le rejeu ne s'arrete que sur des instants ou une bougie vient de
        # se clore : le marche y etait ouvert par construction.
        return MarketState(symbol=symbol, status="OPEN", tradable=True)


def _candle(rates: dict[str, np.ndarray], index: int) -> Candle:
    return Candle(
        time=datetime.fromtimestamp(int(rates["time"][index]), UTC),
        open=float(rates["open"][index]),
        high=float(rates["high"][index]),
        low=float(rates["low"][index]),
        close=float(rates["close"][index]),
        tick_volume=int(rates["tick_volume"][index]),
    )


__all__ = ["HistoricalMarket"]
