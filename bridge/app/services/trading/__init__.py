"""Moteur de trading : execution, gestion des positions, paper trading."""

from app.services.trading.engine import ProcessOutcome, TradingEngine, trading_engine
from app.services.trading.executor import ExecutionOutcome, OrderExecutor, PlacedOrder
from app.services.trading.paper import PaperTradingService
from app.services.trading.position_manager import ManagementResult, PositionManager
from app.services.trading.symbol_resolver import ResolvedSymbol, SymbolResolver

__all__ = [
    "ExecutionOutcome",
    "ManagementResult",
    "OrderExecutor",
    "PaperTradingService",
    "PlacedOrder",
    "PositionManager",
    "ProcessOutcome",
    "ResolvedSymbol",
    "SymbolResolver",
    "TradingEngine",
    "trading_engine",
]
