"""Historique MT5 mis en cache sur disque, pour rejouer sans solliciter le terminal.

Un fichier ``.npz`` par instrument et par unite de temps, sous
``bridge/data/backtest`` (hors depot). Le telechargement se fait par
« les N dernieres bougies » : une plage de dates au-dela de ``maxbars`` fait
renvoyer zero bougie au terminal, sans erreur.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from app.config.settings import BRIDGE_ROOT
from app.models.intelligence import Timeframe
from app.services.mt5.interface import SymbolInfo

CACHE_DIR = BRIDGE_ROOT / "data" / "backtest"
FIELDS = ("time", "open", "high", "low", "close", "tick_volume", "spread")
# Juste sous le ``maxbars`` par defaut du terminal (100 000).
MAX_FETCH = 99_000

_MT5_FRAMES = {
    Timeframe.M1: "TIMEFRAME_M1",
    Timeframe.M5: "TIMEFRAME_M5",
    Timeframe.M15: "TIMEFRAME_M15",
    Timeframe.M30: "TIMEFRAME_M30",
    Timeframe.H1: "TIMEFRAME_H1",
    Timeframe.H4: "TIMEFRAME_H4",
    Timeframe.D1: "TIMEFRAME_D1",
    Timeframe.W1: "TIMEFRAME_W1",
}


def _path(symbol: str, frame: Timeframe) -> Path:
    return CACHE_DIR / f"{symbol}_{frame.value}.npz"


def _info_path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol}_info.json"


def load_rates(symbol: str, frame: Timeframe) -> dict[str, np.ndarray] | None:
    path = _path(symbol, frame)
    if not path.exists():
        return None
    with np.load(path) as data:
        return {name: data[name] for name in FIELDS}


def load_symbol_info(symbol: str) -> SymbolInfo | None:
    path = _info_path(symbol)
    if not path.exists():
        return None
    return SymbolInfo(**json.loads(path.read_text(encoding="utf-8")))


def download(symbols: list[str], frames: list[Timeframe]) -> list[str]:
    """Telecharge et met en cache. Rend une ligne de compte rendu par fichier.

    Ouvre sa propre connexion au terminal : a lancer quand le Bridge tourne,
    le terminal accepte plusieurs clients en lecture.
    """
    import MetaTrader5 as mt5  # absent hors Windows : import tardif

    if not mt5.initialize():
        raise RuntimeError(f"Terminal MT5 inaccessible : {mt5.last_error()}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    report: list[str] = []
    try:
        for symbol in symbols:
            mt5.symbol_select(symbol, True)
            raw_info = mt5.symbol_info(symbol)
            if raw_info is None:
                report.append(f"{symbol} : inconnu du courtier, ignore.")
                continue
            _info_path(symbol).write_text(json.dumps(_info_dict(raw_info)), encoding="utf-8")
            for frame in frames:
                rates = mt5.copy_rates_from_pos(
                    symbol, getattr(mt5, _MT5_FRAMES[frame]), 0, MAX_FETCH
                )
                if rates is None or len(rates) == 0:
                    report.append(f"{symbol} {frame.value} : aucune bougie ({mt5.last_error()}).")
                    continue
                np.savez_compressed(
                    _path(symbol, frame),
                    **{name: np.asarray(rates[name]) for name in FIELDS},
                )
                report.append(f"{symbol} {frame.value} : {len(rates)} bougies.")
    finally:
        mt5.shutdown()
    return report


def _info_dict(raw: Any) -> dict[str, Any]:
    return {
        "name": raw.name,
        "digits": int(raw.digits),
        "point": float(raw.point),
        "trade_tick_size": float(raw.trade_tick_size),
        "trade_tick_value": float(raw.trade_tick_value),
        "trade_contract_size": float(raw.trade_contract_size),
        "volume_min": float(raw.volume_min),
        "volume_max": float(raw.volume_max),
        "volume_step": float(raw.volume_step),
        "trade_stops_level": int(raw.trade_stops_level),
        "trade_freeze_level": int(raw.trade_freeze_level),
        "spread": int(raw.spread),
        "currency_profit": str(raw.currency_profit),
        "currency_margin": str(raw.currency_margin),
    }


__all__ = ["CACHE_DIR", "download", "load_rates", "load_symbol_info"]
