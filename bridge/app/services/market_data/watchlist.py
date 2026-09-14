"""Watchlist : les instruments que TradePilot a le droit d'observer (CDC2 section 17).

Regle absolue : aucun instrument n'est suppose disponible. Chaque ajout passe
par le ``SymbolResolver``, qui interroge la liste reelle des symboles du compte
MetaTrader 5. Un instrument absent est refuse, avec des propositions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.intelligence import WatchlistItem
from app.repositories import market_repo
from app.services.market_data.engine import MarketDataEngine
from app.services.mt5.interface import SymbolInfo
from app.services.signals.symbols import canonical_symbol, strip_broker_suffix
from app.services.trading.symbol_resolver import SymbolResolver

logger = get_logger(__name__)

# Instruments proposes par defaut. Ils ne sont affiches que s'ils existent
# reellement chez le broker : cette liste est une suggestion, pas une promesse.
DEFAULT_WATCHLIST: tuple[str, ...] = (
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "US30",
    "NAS100",
    "SPX500",
    "BTCUSD",
    "XTIUSD",
)

# Nombre maximal de symboles dont on va chercher les metadonnees d'un coup :
# un compte Exness expose parfois plus d'un millier de symboles.
MAX_DETAILED = 40


@dataclass(slots=True)
class SymbolCandidate:
    """Instrument reellement present chez le broker."""

    canonical: str
    broker_symbol: str
    description: str | None = None
    digits: int | None = None
    spread_points: int | None = None
    tradable: bool | None = None
    in_watchlist: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical": self.canonical,
            "brokerSymbol": self.broker_symbol,
            "description": self.description,
            "digits": self.digits,
            "spreadPoints": self.spread_points,
            "tradable": self.tradable,
            "inWatchlist": self.in_watchlist,
        }


@dataclass(slots=True)
class Resolution:
    """Resultat d'une tentative de resolution d'instrument."""

    canonical: str
    broker_symbol: str | None = None
    info: SymbolInfo | None = None
    suggestions: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def available(self) -> bool:
        return self.broker_symbol is not None


class WatchlistService:
    """Consultation du catalogue broker et gestion de la watchlist."""

    def __init__(self, engine: MarketDataEngine, resolver: SymbolResolver | None = None) -> None:
        self._engine = engine
        self._resolver = resolver or SymbolResolver(engine.service)

    @property
    def resolver(self) -> SymbolResolver:
        return self._resolver

    # ------------------------------------------------------------------
    # Catalogue broker
    # ------------------------------------------------------------------
    async def catalogue(self) -> dict[str, str]:
        """Instruments canoniques reellement disponibles -> nom broker.

        Le rapprochement est purement textuel (suffixes broker retires) : il ne
        coute aucun appel supplementaire au terminal.
        """
        names = await self._engine.available_symbols()
        mapping: dict[str, str] = {}
        for name in names:
            canonical = canonical_symbol(name) or canonical_symbol(strip_broker_suffix(name))
            if not canonical:
                continue
            current = mapping.get(canonical)
            if current is None or len(name) < len(current):
                mapping[canonical] = name
        return mapping

    async def describe(
        self, session: AsyncSession, canonicals: list[str], limit: int = MAX_DETAILED
    ) -> list[SymbolCandidate]:
        """Metadonnees reelles d'une courte liste d'instruments."""
        watched = {item.canonical for item in await market_repo.list_watchlist(session)}
        candidates: list[SymbolCandidate] = []
        for canonical in canonicals[: max(1, int(limit))]:
            resolution = await self.resolve(session, canonical, persist=False)
            if not resolution.available or resolution.info is None:
                continue
            info = resolution.info
            candidates.append(
                SymbolCandidate(
                    canonical=resolution.canonical,
                    broker_symbol=info.name,
                    description=info.description or None,
                    digits=info.digits,
                    spread_points=info.spread or None,
                    tradable=info.tradable,
                    in_watchlist=resolution.canonical in watched,
                )
            )
        return candidates

    async def suggested(self, session: AsyncSession) -> list[SymbolCandidate]:
        """Instruments proposes, filtres sur ce que le broker offre vraiment."""
        available = await self.catalogue()
        wanted = [name for name in DEFAULT_WATCHLIST if name in available]
        return await self.describe(session, wanted)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    async def resolve(
        self, session: AsyncSession, symbol: str, persist: bool = True
    ) -> Resolution:
        """Traduit un nom saisi en symbole broker confirme par MT5."""
        raw = (symbol or "").strip()
        canonical = canonical_symbol(raw) or raw.upper()
        if not canonical:
            return Resolution(canonical="", message="Aucun instrument indiqué.")
        try:
            resolved = await self._resolver.resolve(session, canonical, persist=persist)
        except Exception as exc:  # le terminal peut etre indisponible
            logger.warning("Resolution de %s impossible : %s", canonical, exc)
            return Resolution(
                canonical=canonical,
                message="Le terminal MetaTrader 5 n'a pas pu être interrogé.",
            )
        if resolved is None:
            suggestions = await self._resolver.suggestions(canonical)
            return Resolution(
                canonical=canonical,
                suggestions=suggestions,
                message=f"Instrument introuvable chez le broker : {canonical}.",
            )
        return Resolution(
            canonical=canonical,
            broker_symbol=resolved.broker_symbol,
            info=resolved.info,
            message=f"Instrument {canonical} disponible sous le nom {resolved.broker_symbol}.",
        )

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------
    async def add(
        self, session: AsyncSession, symbol: str, **options: Any
    ) -> tuple[WatchlistItem | None, Resolution]:
        """Ajoute un instrument. Refuse si le broker ne le propose pas."""
        resolution = await self.resolve(session, symbol)
        if not resolution.available:
            return None, resolution
        item = await market_repo.upsert_watchlist_item(
            session,
            canonical=resolution.canonical,
            broker_symbol=resolution.broker_symbol,
            available=True,
            **options,
        )
        return item, resolution

    async def refresh(self, session: AsyncSession) -> list[WatchlistItem]:
        """Revalide toute la watchlist aupres du broker.

        Un instrument disparu reste dans la liste mais passe ``available`` a
        faux : il ne sera plus scanne, et l'utilisateur voit pourquoi.
        """
        self._resolver.invalidate()
        items = await market_repo.list_watchlist(session)
        for item in items:
            resolution = await self.resolve(session, item.canonical)
            await market_repo.upsert_watchlist_item(
                session,
                canonical=item.canonical,
                broker_symbol=resolution.broker_symbol,
                available=resolution.available,
            )
        return await market_repo.list_watchlist(session)

    async def scannable(self, session: AsyncSession) -> list[WatchlistItem]:
        """Instruments actifs et confirmes presents : ceux que le scanner lit."""
        items = await market_repo.list_watchlist(session, enabled_only=True)
        return [item for item in items if item.available and item.broker_symbol]


def watchlist_payload(item: WatchlistItem) -> dict[str, Any]:
    """Representation JSON d'une ligne de watchlist."""
    return {
        "id": item.id,
        "symbol": item.canonical,
        "brokerSymbol": item.broker_symbol,
        "enabled": item.enabled,
        "available": item.available,
        "scanPriority": item.scan_priority,
        "allowAiTrading": item.allow_ai_trading,
        "allowTelegramTrading": item.allow_telegram_trading,
        "notifyNews": item.notify_news,
        "notifyOpportunities": item.notify_opportunities,
        "notifyVolatility": item.notify_volatility,
        "lastScannedAt": item.last_scanned_at.isoformat() if item.last_scanned_at else None,
        "addedAt": item.added_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


__all__ = [
    "DEFAULT_WATCHLIST",
    "Resolution",
    "SymbolCandidate",
    "WatchlistService",
    "watchlist_payload",
]
