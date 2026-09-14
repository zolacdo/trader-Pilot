"""Une position nee d'un ordre en attente garde sa reference de risque.

``_promote_order`` transforme un ordre rempli en position suivie. Il copiait le
stop courant mais pas ``initial_stop_loss`` : la position perdait donc la
reference qui definit 1 R.

Consequences constatees le 14/09/2026 sur XAUUSDm #3223262501 :

* le break even en mode R_MULTIPLE teste ``initial_stop_loss is not None`` —
  il ne se declenchait jamais, quel que soit le profit ;
* le resserrement du trailing au-dela de 2 R restait lui aussi inatteignable.

Le stop ne pouvait donc pas remonter tout seul sur les positions entrees par
ordre limite ou stop, c'est-a-dire la majorite des signaux de canaux.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction, ExecutionMode, OrderType, PositionState
from app.models.trading import PendingOrderRecord
from app.services.mt5.interface import PositionInfo, SymbolInfo, TradeResult
from app.services.trading.position_manager import PositionManager

ENTREE = 4310.0
STOP = 4304.0
VOLUME = 0.03


class BrokerMuet:
    """Le strict minimum pour que ``_promote_order`` puisse travailler."""

    async def symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(name=symbol, digits=3, point=0.001)

    async def modify_position(self, ticket, stop_loss, take_profit) -> TradeResult:
        return TradeResult(ok=True, message="ok")


def ordre_en_attente() -> PendingOrderRecord:
    return PendingOrderRecord(
        signal_id=None,
        execution_mode=ExecutionMode.MT5_DEMO,
        ticket=3223262501,
        symbol="XAUUSDm",
        direction=Direction.BUY,
        order_type=OrderType.BUY_LIMIT,
        volume=VOLUME,
        price=ENTREE,
        stop_loss=STOP,
        take_profit=4318.0,
        state=PositionState.PENDING,
    )


def position_remplie() -> PositionInfo:
    return PositionInfo(
        ticket=3223262501,
        symbol="XAUUSDm",
        direction=Direction.BUY,
        volume=VOLUME,
        price_open=ENTREE,
        price_current=ENTREE + 2.0,
        stop_loss=STOP,
        take_profit=4318.0,
        profit=6.0,
    )


class TestReferenceDeRisque:
    async def test_l_ordre_rempli_conserve_son_stop_initial(self, session) -> None:
        """Sans cela, 1 R n'est pas calculable et le break even est mort."""
        manager = PositionManager(BrokerMuet())
        trade = await manager._promote_order(
            session, ordre_en_attente(), position_remplie(), ExecutionMode.MT5_DEMO
        )
        assert trade is not None
        assert trade.initial_stop_loss == pytest.approx(STOP)

    async def test_le_volume_initial_est_conserve(self, session) -> None:
        """Les fermetures partielles se comptent par rapport a ce volume."""
        manager = PositionManager(BrokerMuet())
        trade = await manager._promote_order(
            session, ordre_en_attente(), position_remplie(), ExecutionMode.MT5_DEMO
        )
        assert trade is not None
        assert trade.initial_volume == pytest.approx(VOLUME)

    async def test_un_r_devient_calculable(self, session) -> None:
        """Le point qui compte : la distance de risque doit etre mesurable."""
        manager = PositionManager(BrokerMuet())
        trade = await manager._promote_order(
            session, ordre_en_attente(), position_remplie(), ExecutionMode.MT5_DEMO
        )
        assert trade is not None
        assert trade.initial_stop_loss is not None
        risque = abs(trade.open_price - trade.initial_stop_loss)
        assert risque == pytest.approx(6.0)

    async def test_une_promotion_deja_faite_ne_duplique_pas(self, session) -> None:
        """Le tour suivant ne doit pas creer une seconde position."""
        manager = PositionManager(BrokerMuet())
        premier = await manager._promote_order(
            session, ordre_en_attente(), position_remplie(), ExecutionMode.MT5_DEMO
        )
        assert premier is not None
        second = await manager._promote_order(
            session, ordre_en_attente(), position_remplie(), ExecutionMode.MT5_DEMO
        )
        assert second is None
