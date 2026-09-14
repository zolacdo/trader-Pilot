"""Le break even suit l'objectif franchi, pas le message du canal.

Constate le 14/09/2026 sur le compte demo : XAUUSDm achete a 4286.92, deux
objectifs sur six deja franchis (notification « TP2/6 ATTEINT »), prix a
4293.84 -- et le stop toujours a 4278.61, sous le prix d'entree. Le canal
n'avait poste aucun message de suivi : la progression avait ete constatee par
la lecture du prix, pas annoncee.

Le compteur ``tp_index`` est la seule verite sur « TP1 est atteint ». Peu
importe qui l'a incremente, un message du canal ou la lecture du prix, le
break even doit partir.

Aucun terminal reel : le courtier est simule.
"""

from __future__ import annotations

from app.models.core import RiskSettings
from app.models.enums import BreakEvenTrigger, Direction, PositionState, TrailingMode
from app.models.trading import TradeRecord
from app.services.mt5.interface import SymbolInfo, Tick, TradeResult
from app.services.trading.position_manager import PositionManager

# Les chiffres exacts releves sur le compte.
TICKET = 3223823515
ENTREE = 4286.92
STOP_INITIAL = 4278.61
PRIX_COURANT = 4293.84
CIBLES = [4290.0, 4293.0, 4296.0, 4299.0, 4302.0, 4305.0]


class BrokerSimule:
    """Courtier minimal : accepte toute modification et la garde en memoire."""

    def __init__(self, prix: float) -> None:
        self._prix = prix
        self.modifications: list[tuple[int, float | None, float | None]] = []

    async def symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(name=symbol, digits=2, point=0.01, trade_stops_level=0)

    async def symbol_tick(self, symbol: str) -> Tick:
        return Tick(symbol=symbol, bid=self._prix, ask=self._prix)

    async def modify_position(
        self, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult:
        self.modifications.append((ticket, stop_loss, take_profit))
        return TradeResult(ok=True, message="ok")


def position(tp_index: int) -> TradeRecord:
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
        tp_index=tp_index,
    )


def reglages() -> RiskSettings:
    """Les reglages par defaut de l'application, tels qu'ils tournaient."""
    settings = RiskSettings()
    settings.break_even_enabled = True
    settings.break_even_trigger = BreakEvenTrigger.TP1_HIT
    settings.break_even_offset_points = 5
    settings.trailing_mode = TrailingMode.DISABLED
    return settings


async def test_objectif_franchi_par_le_prix_ramene_le_stop_au_point_mort(session) -> None:
    broker = BrokerSimule(PRIX_COURANT)
    trade = position(tp_index=2)

    await PositionManager(broker).apply_automatic_rules(session, reglages(), [trade])

    attendu = round(ENTREE + 5 * 0.01, 2)
    assert broker.modifications == [(TICKET, attendu, trade.take_profit)]
    assert trade.stop_loss == attendu
    assert trade.break_even_applied is True


async def test_aucun_objectif_franchi_laisse_le_stop_en_place(session) -> None:
    """Sans objectif atteint, le declencheur TP1 ne doit rien faire."""
    broker = BrokerSimule(PRIX_COURANT)
    trade = position(tp_index=0)

    await PositionManager(broker).apply_automatic_rules(session, reglages(), [trade])

    assert broker.modifications == []
    assert trade.stop_loss == STOP_INITIAL
    assert trade.break_even_applied is False
