"""Moteur de Paper Trading.

Reprend integralement la simulation de ``FakeMetaTraderService``, mais utilise
les cotations et les metadonnees REELLES du terminal MT5 lorsqu'il est
connecte. Le paper trading reflete alors le vrai marche et les vraies
contraintes du broker, sans engager le moindre euro (CDC section 71).

Sans terminal disponible, la simulation retombe sur son catalogue interne :
c'est signale explicitement dans le diagnostic, jamais presente comme du reel.
"""

from __future__ import annotations

import contextlib
from typing import Any

from app.config.logging_config import get_logger
from app.models.enums import AccountKind
from app.services.mt5.fake_service import FakeMetaTraderService
from app.services.mt5.interface import AccountInfo, MetaTraderService, SymbolInfo, Tick

logger = get_logger(__name__)


class PaperTradingService(FakeMetaTraderService):
    """Simulateur alimente par les prix reels quand ils sont disponibles."""

    name = "paper"

    def __init__(
        self,
        balance: float = 10000.0,
        currency: str = "USD",
        leverage: int = 500,
        price_source: MetaTraderService | None = None,
    ) -> None:
        super().__init__(
            balance=balance,
            currency=currency,
            leverage=leverage,
            account_kind=AccountKind.DEMO,
            login=99000001,
            server="TradePilot-Paper",
        )
        self._price_source: MetaTraderService | None = price_source
        self._live_prices = False
        self._imported: set[str] = set()

    # ------------------------------------------------------------------
    # Source de prix
    # ------------------------------------------------------------------
    def attach_price_source(self, service: MetaTraderService | None) -> None:
        self._price_source = service
        self._imported.clear()

    @property
    def uses_live_prices(self) -> bool:
        """True si les derniers prix utilises viennent bien du terminal."""
        return self._live_prices

    async def _source_available(self) -> bool:
        if self._price_source is None:
            return False
        try:
            return await self._price_source.is_connected()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Metadonnees et cotations
    # ------------------------------------------------------------------
    async def symbol_info(self, symbol: str) -> SymbolInfo | None:
        if await self._source_available():
            try:
                info = await self._price_source.symbol_info(symbol)
            except Exception:
                info = None
            if info is not None:
                await self._import_symbol(info)
                return info
            # Le terminal repond et ne connait pas ce nom : ne pas retomber sur
            # le catalogue simule, sinon "XAUUSD" existerait a un prix invente
            # alors que le broker cote "XAUUSDm". Le resolveur doit pouvoir
            # essayer les variantes suffixees (CDC section 54).
            return None
        return await super().symbol_info(symbol)

    async def symbol_tick(self, symbol: str) -> Tick | None:
        if await self._source_available():
            try:
                tick = await self._price_source.symbol_tick(symbol)
            except Exception:
                tick = None
            if tick is not None and tick.bid > 0:
                self._live_prices = True
                # Le carnet simule doit voir le meme prix pour declencher SL/TP.
                self.set_price(symbol, tick.bid)
                return tick
            # Meme regle que ci-dessus : pas de cotation inventee tant que le
            # terminal est disponible pour dire la verite.
            self._live_prices = False
            return None
        self._live_prices = False
        return await super().symbol_tick(symbol)

    async def symbols(self) -> list[str]:
        if await self._source_available():
            try:
                names = await self._price_source.symbols()
                if names:
                    return names
            except Exception:
                pass
        return await super().symbols()

    async def ensure_symbol(self, symbol: str) -> bool:
        if await self._source_available():
            with contextlib.suppress(Exception):
                if not await self._price_source.ensure_symbol(symbol):
                    return False
                # Charge les caracteristiques reelles dans le carnet simule.
                info = await self._price_source.symbol_info(symbol)
                if info is not None:
                    await self._import_symbol(info)
        return await super().ensure_symbol(symbol)

    async def _import_symbol(self, info: SymbolInfo) -> None:
        """Copie les caracteristiques broker dans le carnet simule."""
        if info.name in self._imported:
            return
        tick = None
        try:
            tick = await self._price_source.symbol_tick(info.name)
        except Exception:
            tick = None
        price = tick.bid if tick and tick.bid > 0 else None
        if price is None:
            return
        spread_points = tick.spread_points(info.point) if tick else info.spread
        self.add_symbol(info, price, max(1, spread_points))
        self._imported.add(info.name)
        logger.debug("Symbole %s importe dans le moteur papier", info.name)

    # ------------------------------------------------------------------
    # Avancement de la simulation
    # ------------------------------------------------------------------
    async def simulate_step(self) -> list[dict[str, Any]]:
        """Rafraichit les prix reels puis declenche SL/TP et ordres en attente."""
        await self._refresh_open_symbol_prices()
        return self.tick()

    async def _refresh_open_symbol_prices(self) -> None:
        if not await self._source_available():
            return
        names: set[str] = set()
        for position in await super().positions():
            names.add(position.symbol)
        for order in await super().orders():
            names.add(order.symbol)
        for name in names:
            try:
                tick = await self._price_source.symbol_tick(name)
            except Exception:
                continue
            if tick is not None and tick.bid > 0:
                self.set_price(name, tick.bid)

    async def account_info(self) -> AccountInfo | None:
        account = await super().account_info()
        if account is not None:
            # Un compte papier n'est jamais presente comme un compte reel.
            account.name = "Paper Trading"
            account.company = "TradePilot"
        return account
