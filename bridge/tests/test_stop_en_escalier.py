"""Stop en escalier : chaque objectif franchi remonte le stop d'un palier.

Demande du 30/09/2026 : ne rien fermer en route. TP1 atteint, le stop passe a
l'entree ; TP2 atteint, il passe sur TP1 ; TPn atteint, sur TPn-1.

Pourquoi : depuis le 17/09, les gagnants sortaient vers +1 R, rattrapes par
un suiveur ATR serre, et cinq positions (42, 47, 48, 52, 64) passees par TP1
finissaient a zero. L'escalier garde la position entiere et ne cede jamais
plus d'un palier.

Aucun terminal reel : le courtier est simule.
"""

from __future__ import annotations

from app.models.core import RiskSettings
from app.models.enums import BreakEvenTrigger, Direction, PositionState, TrailingMode
from app.models.trading import TradeRecord
from app.services.mt5.interface import SymbolInfo, Tick, TradeResult
from app.services.trading.position_manager import PositionManager

TICKET = 7201
ENTREE = 51409.8
STOP_INITIAL = 51519.8
CIBLES = [51309.8, 51209.8, 51109.8]  # vente US30m, position 72


class BrokerSimule:
    def __init__(self, prix: float) -> None:
        self._prix = prix
        self.modifications: list[tuple[int, float | None, float | None]] = []
        self.fermetures: list[tuple[int, float | None]] = []

    async def symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(name=symbol, digits=1, point=0.1, trade_stops_level=0)

    async def symbol_tick(self, symbol: str) -> Tick:
        return Tick(symbol=symbol, bid=self._prix, ask=self._prix)

    async def modify_position(
        self, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult:
        self.modifications.append((ticket, stop_loss, take_profit))
        return TradeResult(ok=True, message="ok")

    async def close_position(self, ticket: int, volume: float | None = None, deviation: int = 20):
        self.fermetures.append((ticket, volume))
        return TradeResult(ok=True, message="ok")


def vente(tp_index: int, stop: float = STOP_INITIAL) -> TradeRecord:
    return TradeRecord(
        ticket=TICKET,
        symbol="US30m",
        direction=Direction.SELL,
        state=PositionState.OPEN,
        open_price=ENTREE,
        volume=0.06,
        initial_volume=0.06,
        stop_loss=stop,
        initial_stop_loss=STOP_INITIAL,
        take_profit=CIBLES[-1],
        take_profit_targets=list(CIBLES),
        tp_index=tp_index,
    )


def reglages() -> RiskSettings:
    settings = RiskSettings()
    # Le break even reste actif comme en production : l'escalier doit s'y
    # superposer sans conflit.
    settings.break_even_enabled = True
    settings.break_even_trigger = BreakEvenTrigger.TP1_HIT
    settings.break_even_offset_points = 5
    settings.trailing_mode = TrailingMode.TP_LADDER
    return settings


async def test_tp1_franchi_met_le_stop_a_l_entree(session) -> None:
    broker = BrokerSimule(51300.0)
    trade = vente(tp_index=1)

    await PositionManager(broker).apply_automatic_rules(session, reglages(), [trade])

    assert trade.stop_loss == round(ENTREE - 5 * 0.1, 1)
    assert broker.fermetures == []


async def test_tp2_franchi_met_le_stop_sur_tp1(session) -> None:
    broker = BrokerSimule(51200.0)
    trade = vente(tp_index=2, stop=ENTREE)

    await PositionManager(broker).apply_automatic_rules(session, reglages(), [trade])

    assert trade.stop_loss == CIBLES[0]
    assert broker.modifications[-1] == (TICKET, CIBLES[0], CIBLES[-1])
    assert broker.fermetures == []


async def test_deux_paliers_dans_le_meme_tour_vont_directement_au_bon(session) -> None:
    """Le prix saute TP1 et TP2 d'un coup : le stop va sur TP1, pas a l'entree."""
    broker = BrokerSimule(51200.0)
    trade = vente(tp_index=2)

    await PositionManager(broker).apply_automatic_rules(session, reglages(), [trade])

    assert trade.stop_loss == CIBLES[0]
    assert broker.fermetures == []


async def test_le_stop_ne_recule_jamais(session) -> None:
    """Un stop deja au-dela du palier vise n'est pas ramene en arriere."""
    broker = BrokerSimule(51200.0)
    trade = vente(tp_index=2, stop=51250.0)

    await PositionManager(broker).apply_automatic_rules(session, reglages(), [trade])

    assert trade.stop_loss == 51250.0
    assert broker.modifications == []


async def test_aucun_objectif_franchi_ne_bouge_rien(session) -> None:
    broker = BrokerSimule(51380.0)
    trade = vente(tp_index=0)

    await PositionManager(broker).apply_automatic_rules(session, reglages(), [trade])

    assert trade.stop_loss == STOP_INITIAL
    assert broker.modifications == []
