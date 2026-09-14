"""Correspondance symbole canonique -> symbole reellement disponible chez le broker.

Exness expose par exemple ``XAUUSDm``, ``EURUSDz`` ou ``XAUUSD.r`` selon le type
de compte. On ne suppose jamais que le broker utilise le nom canonique : la
liste reelle des symboles MT5 est interrogee, et les correspondances trouvees
sont enregistrees pour etre revues dans l'application (CDC section 54).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.repositories import settings_repo
from app.services.mt5.interface import MetaTraderService, SymbolInfo
from app.services.signals.symbols import clean_token, strip_broker_suffix

logger = get_logger(__name__)

# Suffixes testes en priorite lorsque le nom canonique n'existe pas tel quel.
CANDIDATE_SUFFIXES = ("", "m", "c", "z", "e", ".r", ".a", "micro", "_i", ".p", "pro", "ecn", "#", "+")

# Les indices et quelques matieres premieres ne portent pas le meme nom d'un
# courtier a l'autre : le Nasdaq est USTEC chez Exness, NAS100 ailleurs. Sans
# ces equivalences, un signal NAS100 ne trouve aucun symbole et part en
# SYMBOL_NOT_FOUND alors que l'instrument est bien disponible.
BROKER_ALIASES: dict[str, tuple[str, ...]] = {
    "NAS100": ("USTEC", "NDX100", "USTECH", "NDX"),
    "US30": ("DJ30", "WS30", "DOW30", "USA30"),
    "US500": ("SPX500", "SP500", "USA500"),
    "DE40": ("GER40", "DAX40", "GER30", "DE30"),
    "UK100": ("FTSE100", "GB100"),
    "JP225": ("JPN225", "NIKKEI225"),
    "XAUUSD": ("GOLD",),
    "XAGUSD": ("SILVER",),
}


@dataclass(slots=True)
class ResolvedSymbol:
    canonical: str
    broker_symbol: str
    info: SymbolInfo
    auto_detected: bool = False


class SymbolResolver:
    """Cache en memoire des correspondances, alimente par la base et par MT5."""

    def __init__(self, service: MetaTraderService) -> None:
        self._service = service
        self._cache: dict[str, str] = {}
        self._available: list[str] = []

    async def refresh_available(self) -> list[str]:
        try:
            self._available = await self._service.symbols()
        except Exception as exc:  # le terminal peut etre indisponible
            logger.warning("Liste des symboles MT5 indisponible : %s", exc)
            self._available = []
        return self._available

    def invalidate(self) -> None:
        self._cache.clear()
        self._available = []

    async def candidates_for(self, canonical: str) -> list[str]:
        """Noms broker plausibles pour un symbole canonique, ordonnes."""
        if not self._available:
            await self.refresh_available()
        target = clean_token(canonical)
        exact: list[str] = []
        prefixed: list[str] = []
        loose: list[str] = []
        for name in self._available:
            token = clean_token(name)
            if token == target:
                exact.append(name)
            elif token.startswith(target):
                prefixed.append(name)
            elif strip_broker_suffix(name) == target:
                loose.append(name)
        # Le nom le plus court d'abord : XAUUSD avant XAUUSD.raw
        prefixed.sort(key=len)
        loose.sort(key=len)
        return exact + prefixed + loose

    async def resolve(
        self, session: AsyncSession, canonical: str, persist: bool = True
    ) -> ResolvedSymbol | None:
        """Retourne le symbole broker utilisable, ou None s'il n'existe pas."""
        canonical = canonical.upper()

        if canonical in self._cache:
            info = await self._service.symbol_info(self._cache[canonical])
            if info is not None:
                return ResolvedSymbol(canonical, info.name, info)
            self._cache.pop(canonical, None)

        # 1) correspondance validee par l'utilisateur
        stored = await settings_repo.broker_symbol_for(session, canonical)
        if stored:
            info = await self._ensure(stored)
            if info is not None:
                self._cache[canonical] = info.name
                return ResolvedSymbol(canonical, info.name, info)
            logger.info("Correspondance enregistree %s -> %s invalide chez le broker", canonical, stored)

        # 2) essai direct, puis noms equivalents, chacun avec les suffixes usuels
        for base in (canonical, *BROKER_ALIASES.get(canonical, ())):
            for suffix in CANDIDATE_SUFFIXES:
                info = await self._ensure(f"{base}{suffix}")
                if info is not None:
                    self._cache[canonical] = info.name
                    if persist:
                        await settings_repo.upsert_symbol_mapping(
                            session, canonical, canonical, info.name, auto_detected=True
                        )
                    return ResolvedSymbol(canonical, info.name, info, auto_detected=True)

        # 3) recherche dans la liste complete
        for name in await self.candidates_for(canonical):
            info = await self._ensure(name)
            if info is not None:
                self._cache[canonical] = info.name
                if persist:
                    await settings_repo.upsert_symbol_mapping(
                        session, canonical, canonical, info.name, auto_detected=True
                    )
                return ResolvedSymbol(canonical, info.name, info, auto_detected=True)

        logger.warning("Aucun symbole broker trouve pour %s", canonical)
        return None

    async def _ensure(self, name: str) -> SymbolInfo | None:
        """Selectionne le symbole dans le Market Watch puis lit ses metadonnees."""
        try:
            info = await self._service.symbol_info(name)
            if info is None:
                return None
            if not info.visible:
                await self._service.ensure_symbol(name)
                info = await self._service.symbol_info(name)
            return info
        except Exception:
            return None

    async def suggestions(self, canonical: str, limit: int = 8) -> list[str]:
        """Propositions affichees dans la page Symbol Mapping."""
        return (await self.candidates_for(canonical))[:limit]
