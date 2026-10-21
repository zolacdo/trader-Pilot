"""Le marche rejoue ne montre rien de posterieur a son curseur."""

from __future__ import annotations

import asyncio

import numpy as np

from app.backtest.market import HistoricalMarket
from app.models.intelligence import Timeframe
from app.services.mt5.interface import SymbolInfo

M5 = 300
H1 = 3600


def _rates(start: int, step: int, closes: list[float]) -> dict[str, np.ndarray]:
    n = len(closes)
    close = np.array(closes, dtype=float)
    return {
        "time": start + np.arange(n, dtype=np.int64) * step,
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "tick_volume": np.full(n, 10, dtype=np.int64),
        "spread": np.full(n, 2, dtype=np.int64),
    }


def _market() -> HistoricalMarket:
    # Deux heures de M5 (24 bougies, close = indice) et les deux H1 correspondantes.
    m5 = _rates(0, M5, [float(i) for i in range(24)])
    h1 = _rates(0, H1, [11.0, 23.0])
    return HistoricalMarket("TEST", {Timeframe.M5: m5, Timeframe.H1: h1}, SymbolInfo(name="TEST"))


def test_la_bougie_h1_en_cours_ne_contient_que_le_passe():
    market = _market()
    market.cursor = H1 + 4 * M5  # 1 h 20 : quatre bougies M5 closes dans la 2e heure
    candles = asyncio.run(market.candles("TEST", Timeframe.H1, 10))
    assert len(candles) == 2
    forming = candles[-1]
    # Le fichier dit que la 2e heure cloture a 23 : le rejeu ne doit pas le savoir.
    assert forming.close == 15.0
    assert forming.high == 16.0
    assert int(forming.time.timestamp()) == H1


def test_aucune_bougie_m5_non_close_n_est_rendue():
    market = _market()
    market.cursor = 3 * M5 + 120  # en plein milieu de la 4e bougie
    candles = asyncio.run(market.candles("TEST", Timeframe.M5, 10))
    assert [c.close for c in candles] == [0.0, 1.0, 2.0]


def test_la_cotation_est_celle_de_la_derniere_bougie_close():
    market = _market()
    market.cursor = 6 * M5
    quote = asyncio.run(market.quote("TEST"))
    assert quote is not None
    assert quote.bid == 5.0
    assert quote.spread_points == 2
