"""Couche MetaTrader 5 du Bridge TradePilot.

Deux implementations partagent le meme contrat ``MetaTraderService`` :

* :class:`RealMetaTraderService` pilote le terminal Windows. Le paquet
  ``MetaTrader5`` est isole dans un processus enfant pilote par
  :class:`Mt5ProcessWorker` : un terminal qui ne repond pas est tue et relance
  sans jamais figer le Bridge (l'extension C garde le GIL pendant son IPC).
* :class:`FakeMetaTraderService` simule un terminal en memoire (tests et mode
  PAPER), sans aucune dependance a ``MetaTrader5``.
"""

from __future__ import annotations

from app.services.mt5.fake_service import FakeMetaTraderService
from app.services.mt5.interface import (
    RETCODE_DONE,
    RETCODE_DONE_PARTIAL,
    RETCODE_PLACED,
    AccountInfo,
    Candle,
    DealInfo,
    MetaTraderError,
    MetaTraderNotAvailable,
    MetaTraderService,
    OrderInfo,
    OrderRequest,
    PositionInfo,
    SymbolInfo,
    TerminalInfo,
    Tick,
    TradeResult,
    describe_retcode,
)
from app.services.mt5.process_worker import Mt5ProcessWorker
from app.services.mt5.real_service import RealMetaTraderService, detect_terminals
from app.services.mt5.worker import Mt5Worker

__all__ = [
    "RETCODE_DONE",
    "RETCODE_DONE_PARTIAL",
    "RETCODE_PLACED",
    "AccountInfo",
    "Candle",
    "DealInfo",
    "FakeMetaTraderService",
    "MetaTraderError",
    "MetaTraderNotAvailable",
    "MetaTraderService",
    "Mt5ProcessWorker",
    "Mt5Worker",
    "OrderInfo",
    "OrderRequest",
    "PositionInfo",
    "RealMetaTraderService",
    "SymbolInfo",
    "TerminalInfo",
    "Tick",
    "TradeResult",
    "describe_retcode",
    "detect_terminals",
]
