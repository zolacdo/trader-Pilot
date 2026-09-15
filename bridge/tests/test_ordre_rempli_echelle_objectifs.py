"""Une position nee d'un ordre en attente garde son echelle d'objectifs.

``_promote_order`` copiait le stop, le volume et le take profit unique, mais
pas ``take_profit_targets``. La position naissait donc avec une liste vide, et
toute la gestion automatique s'eteignait en cascade :

    take_profit_targets = []
      -> aucune fermeture partielle (position_manager.py, PARTIAL_CLOSE)
      -> tp_index reste a 0
      -> break_even_trigger = TP1_HIT lit `tp_index >= 1`
      -> le stop ne remonte JAMAIS

Constate en base le 14/09/2026 : les cinq pertes issues d'ordres en attente
portaient toutes ``take_profit_targets = []``, ``tp_index = 0`` et un
``stop_loss`` encore egal a ``initial_stop_loss``. La seule position ayant
conserve ses objectifs (#3225843673, EURUSD) etait aussi la seule entree au
marche. Sur 23 trades, ``break_even_applied`` n'etait vrai que deux fois.

Ce que cela coute se lit sur le watcher, qui suit les memes signaux sans
gestion : #7 (US500) a franchi TP1 a +1,27 R puis est reparti jusqu'au stop,
#10 (ETHUSD) a franchi TP1 a +1,08 R avant de finir a -1 R.

Deux sources, dans cet ordre : l'echelle inscrite sur l'ordre, puis celle du
signal d'origine -- cette seconde voie repare les ordres deja poses avant le
correctif, qui n'ont pas la colonne renseignee.
"""

from __future__ import annotations

import pytest

from app.models.enums import (
    Direction,
    ExecutionMode,
    OrderType,
    PositionState,
    SignalStatus,
)
from app.models.trading import PendingOrderRecord, Signal
from app.services.mt5.interface import PositionInfo, SymbolInfo, TradeResult
from app.services.trading.position_manager import PositionManager

ENTREE = 4267.0
STOP = 4255.0
VOLUME = 0.04
ECHELLE = [4270.0, 4273.0, 4276.0, 4279.0, 4282.0, 4285.0]


class BrokerMuet:
    """Le strict minimum pour que ``_promote_order`` puisse travailler."""

    async def symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(name=symbol, digits=3, point=0.001)

    async def modify_position(self, ticket, stop_loss, take_profit) -> TradeResult:
        return TradeResult(ok=True, message="ok")


def ordre(**kwargs: object) -> PendingOrderRecord:
    """L'ordre du signal 190 : XAUUSDm BUY_LIMIT, six objectifs."""
    base: dict[str, object] = {
        "signal_id": None,
        "execution_mode": ExecutionMode.MT5_DEMO,
        "ticket": 3225201437,
        "symbol": "XAUUSDm",
        "direction": Direction.BUY,
        "order_type": OrderType.BUY_LIMIT,
        "volume": VOLUME,
        "price": ENTREE,
        "stop_loss": STOP,
        "take_profit": ECHELLE[-1],
        "state": PositionState.PENDING,
    }
    base.update(kwargs)
    return PendingOrderRecord(**base)  # type: ignore[arg-type]


def position_remplie() -> PositionInfo:
    return PositionInfo(
        ticket=3225201437,
        symbol="XAUUSDm",
        direction=Direction.BUY,
        volume=VOLUME,
        price_open=ENTREE,
        price_current=ENTREE + 1.0,
        stop_loss=STOP,
        take_profit=ECHELLE[-1],
        profit=4.0,
    )


_compteur = 0


async def _signal_en_base(session, cibles: list[float]) -> int:
    global _compteur
    _compteur += 1
    signal = Signal(
        idempotency_key=f"echelle-{_compteur}",
        symbol="XAUUSD",
        normalized_symbol="XAUUSD",
        broker_symbol="XAUUSDm",
        direction=Direction.BUY,
        entry_price=ENTREE,
        stop_loss=STOP,
        take_profits=list(cibles),
        status=SignalStatus.SENT,
        confidence=0.95,
    )
    session.add(signal)
    await session.flush()
    assert signal.id is not None
    return signal.id


async def _promouvoir(session, commande: PendingOrderRecord):
    return await PositionManager(BrokerMuet())._promote_order(
        session, commande, position_remplie(), ExecutionMode.MT5_DEMO
    )


class TestEchellePorteeParLOrdre:
    async def test_les_objectifs_de_l_ordre_sont_repris(self, session) -> None:
        trade = await _promouvoir(session, ordre(take_profit_targets=list(ECHELLE)))
        assert trade is not None
        assert trade.take_profit_targets == ECHELLE

    async def test_la_gestion_automatique_redevient_possible(self, session) -> None:
        """Le point qui compte : sans echelle, tp_index ne peut pas avancer."""
        trade = await _promouvoir(session, ordre(take_profit_targets=list(ECHELLE)))
        assert trade is not None
        assert trade.tp_index < len(trade.take_profit_targets)


class TestReparationDepuisLeSignal:
    async def test_un_ordre_sans_echelle_la_recupere_du_signal(self, session) -> None:
        """Repare les ordres deja poses avant le correctif."""
        signal_id = await _signal_en_base(session, ECHELLE)
        trade = await _promouvoir(session, ordre(signal_id=signal_id))
        assert trade is not None
        assert trade.take_profit_targets == ECHELLE

    async def test_l_echelle_de_l_ordre_prime_sur_celle_du_signal(self, session) -> None:
        """L'ordre porte ce qui a ete reellement envoye au courtier."""
        signal_id = await _signal_en_base(session, [4300.0, 4310.0])
        trade = await _promouvoir(
            session, ordre(signal_id=signal_id, take_profit_targets=list(ECHELLE))
        )
        assert trade is not None
        assert trade.take_profit_targets == ECHELLE


class TestAucuneEchelleDisponible:
    async def test_sans_signal_ni_echelle_la_promotion_reussit(self, session) -> None:
        """Un ordre pose a la main n'a jamais eu d'objectifs : pas d'erreur."""
        trade = await _promouvoir(session, ordre())
        assert trade is not None
        assert trade.take_profit_targets == []

    async def test_un_signal_sans_objectifs_ne_casse_rien(self, session) -> None:
        signal_id = await _signal_en_base(session, [])
        trade = await _promouvoir(session, ordre(signal_id=signal_id))
        assert trade is not None
        assert trade.take_profit_targets == []

    async def test_le_take_profit_unique_reste_pose(self, session) -> None:
        """On ne perd pas l'objectif deja transmis au courtier."""
        trade = await _promouvoir(session, ordre())
        assert trade is not None
        assert trade.take_profit == pytest.approx(ECHELLE[-1])
