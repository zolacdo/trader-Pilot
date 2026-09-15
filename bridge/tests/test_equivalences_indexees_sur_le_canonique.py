"""Les equivalences broker doivent etre indexees sur le nom canonique reel.

``SymbolResolver.resolve`` ne consulte ``BROKER_ALIASES`` que par
``BROKER_ALIASES.get(canonical)``. Une entree dont la CLE n'est pas un nom
canonique produit par ``canonical_symbol`` n'est donc jamais lue : elle est
morte, et l'instrument reste introuvable chez le courtier.

Constate le 15/09/2026 sur un signal SPX500 refuse « Instrument introuvable
chez le broker », alors qu'Exness expose bien ``US500m`` -- la correspondance
avait meme ete auto-detectee le 12/09.

    canonical_symbol("SPX500")  -> "SPX500"   (et US500, SP500, SPX aussi)
    BROKER_ALIASES cle          -> "US500"    <- jamais atteinte

Meme inversion sur le DAX : le canonique est ``GER40``, la cle etait ``DE40``.

Les tests d'equivalence existants passaient parce qu'ils appelaient
``resolve(session, "DE40")`` directement, sans passer par le normaliseur. Le
garde-fou qui manquait est celui qui relie les deux modules.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.signals.symbols import canonical_symbol
from app.services.trading.symbol_resolver import BROKER_ALIASES, SymbolResolver
from tests.test_equivalences_broker import CourtierFictif


class TestLesClesSontDesCanoniques:
    @pytest.mark.parametrize("cle", sorted(BROKER_ALIASES))
    def test_chaque_cle_est_le_canonique_d_elle_meme(self, cle: str) -> None:
        """Sans cela, l'entree n'est jamais consultee par le resolveur."""
        assert canonical_symbol(cle) == cle

    @pytest.mark.parametrize("cle", sorted(BROKER_ALIASES))
    def test_les_equivalents_designent_bien_le_meme_instrument(self, cle: str) -> None:
        """Un equivalent qui normalise ailleurs ferait trader le mauvais actif."""
        for equivalent in BROKER_ALIASES[cle]:
            resolu = canonical_symbol(equivalent)
            assert resolu in (cle, None), (
                f"{equivalent} est donne comme equivalent de {cle} "
                f"mais se normalise en {resolu}"
            )


class TestLeCasConstateEnProduction:
    async def test_spx500_se_resout_en_us500m(self, session: AsyncSession) -> None:
        """Le signal du 15/09 : SPX500 SELL, refuse a tort."""
        courtier = CourtierFictif(["US500m", "XAUUSDm", "US30m"])
        resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

        resolu = await resolveur.resolve(session, "SPX500")

        assert resolu is not None, f"essais : {courtier.demandes}"
        assert resolu.broker_symbol == "US500m"
        assert resolu.canonical == "SPX500"

    @pytest.mark.parametrize("alias", ["SPX500", "US500", "SP500", "SPX"])
    async def test_toutes_les_ecritures_du_sp500_aboutissent(
        self, session: AsyncSession, alias: str
    ) -> None:
        """Quel que soit le nom employe par le canal, l'instrument est trouve."""
        canonique = canonical_symbol(alias)
        assert canonique is not None

        courtier = CourtierFictif(["US500m"])
        resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

        resolu = await resolveur.resolve(session, canonique)

        assert resolu is not None, f"{alias} -> {canonique} ; essais : {courtier.demandes}"
        assert resolu.broker_symbol == "US500m"

    async def test_le_dax_se_resout_sous_son_nom_courtier(
        self, session: AsyncSession
    ) -> None:
        """Meme inversion que le S&P : canonique GER40, cle posee sur DE40."""
        courtier = CourtierFictif(["DE40m"])
        resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

        resolu = await resolveur.resolve(session, "GER40")

        assert resolu is not None, f"essais : {courtier.demandes}"
        assert resolu.broker_symbol == "DE40m"


class TestLeResolveurNormaliseSaSaisie:
    """Tous les appelants ne passent pas un canonique.

    ``/market/symbols?search=`` transmet la saisie brute de l'utilisateur. Sans
    normalisation interne, une recherche « DE40 » ou « SP500 » n'atteindrait
    aucune equivalence, puisqu'elles sont indexees sur le canonique.
    """

    @pytest.mark.parametrize("saisie", ["DE40", "dax40", "GER30"])
    async def test_une_ecriture_non_canonique_aboutit(
        self, session: AsyncSession, saisie: str
    ) -> None:
        courtier = CourtierFictif(["GER40m"])
        resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

        resolu = await resolveur.resolve(session, saisie)

        assert resolu is not None, f"essais : {courtier.demandes}"
        assert resolu.broker_symbol == "GER40m"
        assert resolu.canonical == "GER40"

    async def test_un_nom_inconnu_du_normaliseur_est_conserve(
        self, session: AsyncSession
    ) -> None:
        """Un symbole propre au courtier doit rester cherchable tel quel."""
        courtier = CourtierFictif(["XBRUSDm"])
        resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

        resolu = await resolveur.resolve(session, "XBRUSD")

        assert resolu is not None, f"essais : {courtier.demandes}"
        assert resolu.broker_symbol == "XBRUSDm"


class TestAucuneInventionDeCorrespondance:
    async def test_un_indice_absent_reste_introuvable(
        self, session: AsyncSession
    ) -> None:
        """Elargir les equivalences ne doit pas fabriquer de faux positifs."""
        courtier = CourtierFictif(["EURUSDm", "XAUUSDm"])
        resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

        assert await resolveur.resolve(session, "SPX500") is None

    async def test_le_sp500_ne_se_resout_pas_sur_le_dow(
        self, session: AsyncSession
    ) -> None:
        """US30m ne doit jamais servir de repli pour le S&P 500."""
        courtier = CourtierFictif(["US30m"])
        resolveur = SymbolResolver(courtier)  # type: ignore[arg-type]

        assert await resolveur.resolve(session, "SPX500") is None
