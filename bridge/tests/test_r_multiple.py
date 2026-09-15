"""1 R vaut le montant reellement risque, pas une distance de prix.

Constate en base le 14/09/2026 : les quatre positions parties au stop du jour
affichaient -100, -100, -99,989 et -100000 R. Toutes avaient perdu exactement
leur risque initial, donc -1 R.

La formule fautive (``engine.py``) divisait un resultat en dollars par
``distance de prix x volume``, qui n'est pas un montant : il manque la taille
du contrat. L'erreur vaut donc le contrat du symbole -- 100 sur l'or,
100 000 sur l'euro -- ce qui explique la valeur -100000 du trade #3225843673.

Ce chiffre n'est pas cosmetique : il alimente les statistiques par canal, la
performance par strategie et l'affichage de l'application. Un R faux, c'est un
systeme qui apprend sur des donnees fausses.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction, ExecutionMode, PositionState
from app.models.trading import TradeRecord
from app.services.mt5.fake_service import FakeMetaTraderService
from app.services.trading.engine import trading_engine


@pytest.fixture
async def mt5() -> FakeMetaTraderService:
    service = FakeMetaTraderService(balance=540.41)
    await service.initialize()
    return service


def _position(**kwargs: object) -> TradeRecord:
    """Le trade #3225201437 : XAUUSD 0,04 lot, stop a 12 dollars, parti au stop.

    Taille du contrat de l'or : 100. Le risque vaut donc
    12 x 0,04 x 100 = 48 dollars, et c'est exactement ce qu'il a perdu.
    """
    base: dict[str, object] = {
        "ticket": 3225201437,
        "symbol": "XAUUSD",
        "direction": Direction.BUY,
        "execution_mode": ExecutionMode.MT5_DEMO,
        "state": PositionState.CLOSED,
        "open_price": 4267.0,
        "initial_stop_loss": 4255.0,
        "initial_volume": 0.04,
        "volume": 0.04,
        "realized_pnl": -48.0,
    }
    base.update(kwargs)
    return TradeRecord(**base)  # type: ignore[arg-type]


class TestRisqueDeReference:
    async def test_le_risque_est_un_montant_en_devise(
        self, mt5: FakeMetaTraderService
    ) -> None:
        reference = await trading_engine.risk_reference(mt5, _position())
        assert reference == pytest.approx(48.0)

    async def test_sans_stop_initial_aucune_reference(
        self, mt5: FakeMetaTraderService
    ) -> None:
        """Une position reprise chez le courtier peut ne pas en avoir."""
        reference = await trading_engine.risk_reference(
            mt5, _position(initial_stop_loss=None)
        )
        assert reference is None

    async def test_un_stop_confondu_avec_lentree_ne_donne_aucune_reference(
        self, mt5: FakeMetaTraderService
    ) -> None:
        reference = await trading_engine.risk_reference(
            mt5, _position(initial_stop_loss=4267.0)
        )
        assert reference is None

    async def test_un_symbole_inconnu_ne_fait_pas_echouer_le_cycle(
        self, mt5: FakeMetaTraderService
    ) -> None:
        reference = await trading_engine.risk_reference(
            mt5, _position(symbol="INEXISTANT")
        )
        assert reference is None


class TestValeurDuRMultiple:
    async def test_une_position_partie_au_stop_vaut_moins_un_r(
        self, mt5: FakeMetaTraderService
    ) -> None:
        trade = _position()
        reference = await trading_engine.risk_reference(mt5, trade)
        assert reference is not None
        assert round(trade.realized_pnl / reference, 3) == -1.0

    async def test_un_gain_de_deux_fois_le_risque_vaut_deux_r(
        self, mt5: FakeMetaTraderService
    ) -> None:
        trade = _position(realized_pnl=96.0)
        reference = await trading_engine.risk_reference(mt5, trade)
        assert reference is not None
        assert round(trade.realized_pnl / reference, 3) == 2.0

    async def test_leuro_ne_produit_plus_cent_mille_r(
        self, mt5: FakeMetaTraderService
    ) -> None:
        """Le trade #3225843673 : 0,34 lot, stop a 125 points, -43,18 dollars.

        Contrat de 100 000 : 0,00125 x 0,34 x 100 000 = 42,50 dollars risques.
        L'ancienne formule renvoyait -100000.
        """
        trade = _position(
            symbol="EURUSD",
            direction=Direction.SELL,
            open_price=1.15262,
            initial_stop_loss=1.15387,
            initial_volume=0.34,
            volume=0.34,
            realized_pnl=-42.50,
        )
        reference = await trading_engine.risk_reference(mt5, trade)
        assert reference == pytest.approx(42.50, abs=0.01)
        assert round(trade.realized_pnl / reference, 3) == -1.0
