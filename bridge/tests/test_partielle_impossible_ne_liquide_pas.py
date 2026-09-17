"""Une prise partielle impossible ne doit pas liquider la position.

Constate le 16/09/2026 sur le compte demo, position 35 : XAUUSDm achete a
4337.00 pour 0,01 lot, stop a 4327.00, objectifs a 4343 / 4346 / 4349 /
4352 / 4355. TP1 franchi, et la position entiere fermee une minute
cinquante plus tard pour -0,49 $ -- avec le motif « prise partielle sur
TP1 » et le stop toujours a 4327.00, jamais remonte.

La cause est un choix explicite de ``_close_partial`` : quand 40 % du volume
tombe sous le minimum du courtier -- ce qui est toujours le cas a 0,01 lot,
puisque 0,004 n'existe pas -- il fermait tout « a la place ».

Or la mesure du 17/09/2026 sur les 41 signaux denoues dit que la totalite du
profit vient des cinq signaux qui depassent 2,5 R : les quatorze autres font
-1,07 R ensemble. Liquider au premier objectif detruit donc exactement la
seule source de gain, et sur les petites positions la strategie 40/30/30 se
reduisait a « sortir a TP1 » -- voire a sortir en perte quand le prix
revenait entre le declenchement et l'execution, ce qui est arrive ici.

Ne rien fermer est strictement meilleur : l'objectif du partiel est de
reduire le risque, et le break even qui suit immediatement dans
``_handle_tp_hit`` l'atteint tout aussi bien en mettant le stop a l'entree,
sans renoncer a la suite du mouvement.

Aucun terminal reel : le courtier est simule.
"""

from __future__ import annotations

from app.models.core import RiskSettings
from app.models.enums import (
    BreakEvenTrigger,
    Direction,
    MultiTpStrategy,
    PositionState,
    TrailingMode,
)
from app.models.trading import TradeRecord
from app.services.mt5.interface import SymbolInfo, Tick, TradeResult
from app.services.trading.position_manager import ManagementResult, PositionManager

# Les chiffres exacts de la position 35.
TICKET = 3237395116
ENTREE = 4337.00
STOP_INITIAL = 4327.00
CIBLES = [4343.0, 4346.0, 4349.0, 4352.0, 4355.0]


class BrokerSimule:
    """Courtier minimal. Il retient toute fermeture, c'est ce qu'on surveille."""

    def __init__(self, prix: float) -> None:
        self._prix = prix
        self.fermetures: list[tuple[int, float | None]] = []
        self.modifications: list[tuple[int, float | None, float | None]] = []

    async def symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(
            name=symbol,
            digits=2,
            point=0.01,
            trade_stops_level=0,
            volume_min=0.01,
            volume_step=0.01,
        )

    async def symbol_tick(self, symbol: str) -> Tick:
        return Tick(symbol=symbol, bid=self._prix, ask=self._prix)

    async def close_position(self, ticket: int, volume: float | None = None) -> TradeResult:
        self.fermetures.append((ticket, volume))
        return TradeResult(ok=True, message="ok", volume=volume)

    async def modify_position(
        self, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult:
        self.modifications.append((ticket, stop_loss, take_profit))
        return TradeResult(ok=True, message="ok")


def position() -> TradeRecord:
    return TradeRecord(
        ticket=TICKET,
        symbol="XAUUSDm",
        direction=Direction.BUY,
        state=PositionState.OPEN,
        open_price=ENTREE,
        volume=0.01,
        initial_volume=0.01,
        stop_loss=STOP_INITIAL,
        initial_stop_loss=STOP_INITIAL,
        take_profit_targets=list(CIBLES),
        tp_index=0,
    )


def reglages() -> RiskSettings:
    """Les reglages du compte au moment des faits."""
    settings = RiskSettings()
    settings.multi_tp_strategy = MultiTpStrategy.PARTIAL_CLOSE
    settings.split_ratios = [40.0, 30.0, 30.0]
    settings.break_even_enabled = True
    settings.break_even_trigger = BreakEvenTrigger.TP1_HIT
    settings.break_even_offset_points = 5
    settings.trailing_mode = TrailingMode.DISABLED
    return settings


async def test_un_lot_minimum_n_est_pas_liquide_au_premier_objectif(session) -> None:
    """Le coeur : a 0,01 lot, TP1 franchi ne doit fermer aucun volume."""
    broker = BrokerSimule(CIBLES[0])
    trade = position()

    await PositionManager(broker)._handle_tp_hit(
        session, trade, 1, reglages(), ManagementResult()
    )

    assert broker.fermetures == []
    assert trade.state is PositionState.OPEN
    assert trade.volume == 0.01


async def test_le_stop_protege_la_position_restee_ouverte(session) -> None:
    """Le risque est reduit par le stop, pas par la liquidation.

    C'est la contrepartie du test precedent : ne pas fermer ne doit pas
    laisser la position sans protection, sinon on aurait remplace une sortie
    trop prompte par une position nue.
    """
    broker = BrokerSimule(CIBLES[0])
    trade = position()

    await PositionManager(broker)._handle_tp_hit(
        session, trade, 1, reglages(), ManagementResult()
    )

    attendu = round(ENTREE + 5 * 0.01, 2)
    assert trade.break_even_applied is True
    assert trade.stop_loss == attendu
    assert broker.modifications == [(TICKET, attendu, trade.take_profit)]


async def test_une_partielle_possible_reste_prise(session) -> None:
    """La barriere ne vise que l'impossible : a 0,10 lot le partiel part.

    Sans ce test, supprimer la prise partielle entierement passerait aussi.
    """
    broker = BrokerSimule(CIBLES[0])
    trade = position()
    trade.volume = 0.10
    trade.initial_volume = 0.10

    await PositionManager(broker)._handle_tp_hit(
        session, trade, 1, reglages(), ManagementResult()
    )

    assert broker.fermetures == [(TICKET, 0.04)]
    assert trade.state is PositionState.PARTIALLY_CLOSED
