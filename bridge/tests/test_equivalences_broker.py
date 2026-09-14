"""Un indice doit etre trouve meme si le courtier lui donne un autre nom.

Mesure sur le compte Exness reel le 11/09/2026 : ``USTECm`` existe, ``NAS100m``
n'existe pas. Le resolveur n'essayait que le nom canonique suivi des suffixes
usuels, donc tout signal NAS100 partait en SYMBOL_NOT_FOUND alors que
l'instrument etait disponible.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.mt5.interface import SymbolInfo
from app.services.trading.symbol_resolver import BROKER_ALIASES, SymbolResolver


class CourtierFictif:
    """N'expose que les noms qu'on lui donne, comme le ferait un vrai terminal."""

    def __init__(self, noms: list[str]) -> None:
        self.noms = noms
        self.demandes: list[str] = []

    async def symbol_info(self, name: str) -> SymbolInfo | None:
        self.demandes.append(name)
        if name not in self.noms:
            return None
        return SymbolInfo(
            name=name,
            digits=2,
            point=0.01,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_contract_size=1.0,
            trade_tick_value=0.01,
            trade_tick_size=0.01,
            trade_stops_level=0,
        )

    async def symbols(self) -> list[str]:
        return list(self.noms)


async def test_le_nasdaq_est_trouve_sous_son_nom_exness(session: AsyncSession) -> None:
    """NAS100 doit se resoudre en USTECm, le nom reel chez Exness."""
    courtier = CourtierFictif(["USTECm", "XAUUSDm", "EURUSDm"])
    resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

    resolu = await resolveur.resolve(session, "NAS100")

    assert resolu is not None, f"aucun symbole trouve ; essais : {courtier.demandes}"
    assert resolu.broker_symbol == "USTECm"
    assert resolu.canonical == "NAS100"


async def test_le_nom_canonique_reste_prioritaire(session: AsyncSession) -> None:
    """Si le courtier expose le nom canonique, on ne part pas chercher ailleurs."""
    courtier = CourtierFictif(["NAS100m", "USTECm"])
    resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

    resolu = await resolveur.resolve(session, "NAS100")

    assert resolu is not None
    assert resolu.broker_symbol == "NAS100m"


@pytest.mark.parametrize(
    ("canonique", "nom_courtier"),
    [
        ("US30", "DJ30m"),
        ("DE40", "GER40m"),
        ("XAUUSD", "GOLDm"),
    ],
)
async def test_les_autres_equivalences_fonctionnent(
    session: AsyncSession, canonique: str, nom_courtier: str
) -> None:
    courtier = CourtierFictif([nom_courtier])
    resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

    resolu = await resolveur.resolve(session, canonique)

    assert resolu is not None, f"essais : {courtier.demandes}"
    assert resolu.broker_symbol == nom_courtier


async def test_un_symbole_reellement_absent_reste_introuvable(session: AsyncSession) -> None:
    """Les equivalences ne doivent pas inventer de correspondance."""
    courtier = CourtierFictif(["EURUSDm"])
    resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

    assert await resolveur.resolve(session, "NAS100") is None


def test_aucune_equivalence_ne_pointe_vers_un_autre_canonique() -> None:
    """Garde-fou : une equivalence mal placee ferait trader le mauvais actif.

    Si « GOLD » apparaissait comme equivalent de XAGUSD, un signal argent
    ouvrirait une position sur l'or.
    """
    canoniques = set(BROKER_ALIASES)
    for canonique, equivalents in BROKER_ALIASES.items():
        for equivalent in equivalents:
            assert equivalent not in canoniques - {canonique}, (
                f"{equivalent} est equivalent de {canonique} mais aussi un canonique"
            )
