"""Fourniture du moteur de donnees adosse au service de marche actif.

MetaTrader 5 est prioritaire (CDC2 section 16). Si le terminal n'est pas
attache, le simulateur prend le relais : les analyses restent possibles, et
l'appelant sait toujours de quelle source elles proviennent.
"""

from __future__ import annotations

from app.services.market_data.engine import MarketDataEngine
from app.services.mt5.interface import MetaTraderService

# Un seul service de marche est actif a la fois : on garde son moteur pour
# profiter du cache de bougies d'un appel a l'autre.
_current: tuple[MetaTraderService, MarketDataEngine] | None = None


def active_market_service() -> MetaTraderService | None:
    """Service de marche a interroger : MT5 s'il est attache, sinon PAPER."""
    from app.services.trading.engine import trading_engine

    return trading_engine.market or trading_engine.paper


def market_engine(service: MetaTraderService | None = None) -> MarketDataEngine | None:
    """Moteur de donnees du service demande, ou du service actif."""
    global _current
    target = service or active_market_service()
    if target is None:
        return None
    if _current is not None and _current[0] is target:
        return _current[1]
    _current = (target, MarketDataEngine(target))
    return _current[1]


def reset_market_engine() -> None:
    """Oublie le moteur memorise (changement de compte, tests)."""
    global _current
    _current = None


__all__ = ["active_market_service", "market_engine", "reset_market_engine"]
