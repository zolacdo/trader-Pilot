"""Fournisseur de bougies par plage de dates, bati sur le moteur de marche.

Les moteurs d'analogues historiques et de correlations demandent une plage de
dates. Le terminal MetaTrader, lui, ne doit plus etre interroge de cette
facon : ``copy_rates_range`` le force a rapatrier l'historique manquant depuis
le serveur du courtier, ce qui l'a deja bloque assez longtemps pour que le
chien de garde tue le processus.

Cet adaptateur fait le pont : il demande « les N dernieres bougies », ce que le
terminal sert immediatement, puis ne garde que celles qui tombent dans la
plage voulue. Il ne fabrique jamais de bougie manquante — une periode sans
donnee ressort vide, et les moteurs en aval savent quoi en faire.
"""

from __future__ import annotations

from datetime import datetime

from app.config.logging_config import get_logger
from app.models.core import as_utc
from app.services.market_data.engine import (
    MAX_BARS,
    TIMEFRAME_MINUTES,
    MarketDataEngine,
    parse_timeframe,
)
from app.services.mt5.interface import Candle

logger = get_logger(__name__)

# Marge appliquee au nombre de bougies demande. Le marche ferme le week-end et
# les jours feries : une plage de N periodes contient donc moins de N bougies,
# et en demander le compte exact en laisserait tomber au debut.
MARGE_CALENDAIRE = 1.8


class RangeCandleProvider:
    """Sert une API par plage de dates depuis un moteur « N dernieres bougies »."""

    def __init__(self, engine: MarketDataEngine, *, broker_symbol: str | None = None) -> None:
        self._engine = engine
        # Certains moteurs attendent le nom du courtier (« XAUUSDm ») la ou
        # l'analyse raisonne en nom canonique (« XAUUSD »).
        self._broker_symbol = broker_symbol

    async def candles(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:
        """Bougies de ``symbol`` comprises entre ``start`` et ``end``."""
        frame = parse_timeframe(timeframe)
        if frame is None:
            return []
        minutes = TIMEFRAME_MINUTES.get(frame)
        if not minutes:
            return []

        debut = as_utc(start)
        fin = as_utc(end)
        if debut is None or fin is None or fin <= debut:
            return []

        periodes = (fin - debut).total_seconds() / 60.0 / minutes
        voulues = min(MAX_BARS, max(10, int(periodes * MARGE_CALENDAIRE) + 5))

        cible = self._broker_symbol or symbol
        try:
            serie = await self._engine.candles(cible, frame, bars=voulues)
        except Exception as exc:
            logger.debug("Bougies %s %s indisponibles : %s", cible, frame.value, exc)
            return []

        return [
            bougie
            for bougie in serie
            if (moment := as_utc(bougie.time)) is not None and debut <= moment <= fin
        ]


__all__ = ["MARGE_CALENDAIRE", "RangeCandleProvider"]
