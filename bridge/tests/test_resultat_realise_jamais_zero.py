"""Un zero du courtier n'est pas un equilibre quand la position a bouge.

Constate le 18/09/2026 sur le compte demo, position 44 : BTCUSDm vendu
0,02 lot, stop touche, ``profit`` a -3,91 et ``r_multiple`` a -1,00 -- mais
``realized_pnl`` a **0,00**. La perte reelle du jour etait bien de 3,91 $.

La cause : ``sync_with_broker`` lit l'historique des deals AVANT de detecter
les fermetures. Au moment de la lecture, le deal d'entree de la position
etait visible (profit nul) mais pas encore celui de sortie -- l'historique du
courtier a un temps de retard sur la disparition de la position. La somme
valait donc 0,0, et ``realized.get(ticket, trade.profit)`` renvoie ce zero
stocke au lieu de retomber sur ``profit`` : le repli ne pouvait jamais jouer.

Ce que ce zero abime :

* les statistiques de l'application -- ``statistics/service.py`` compte un
  ``realized_pnl == 0`` comme un trade a l'equilibre, donc une perte pleine
  disparaissait du taux de reussite et du profit factor ;
* la lecture des pertes, qui est tout l'objet de la boucle de retour.

Une position fermee qui portait un resultat flottant non nul ne peut pas
avoir realise exactement zero. Dans ce cas le flottant est la meilleure
mesure disponible, et un chiffre approche vaut mieux qu'un zero faux.
"""

from __future__ import annotations

from app.models.core import utcnow
from app.models.enums import Direction, ExecutionMode, PositionState
from app.models.trading import TradeRecord
from app.services.mt5.interface import DealInfo
from app.services.trading.position_manager import PositionManager

TICKET = 3247618250
PROFIT_FLOTTANT = -3.91


class BrokerSansDealDeSortie:
    """Courtier dont l'historique ne montre que le deal d'entree.

    C'est l'etat reel au moment ou la reconciliation lit l'historique : la
    position a disparu, son deal de cloture n'est pas encore publie.
    """

    def __init__(self, deals: list[DealInfo] | None = None) -> None:
        self._deals = deals if deals is not None else []

    async def positions(self) -> list[object]:
        return []

    async def history_deals(self, depuis: object) -> list[DealInfo]:
        return list(self._deals)


def position() -> TradeRecord:
    return TradeRecord(
        ticket=TICKET,
        symbol="BTCUSDm",
        direction=Direction.SELL,
        state=PositionState.OPEN,
        execution_mode=ExecutionMode.MT5_DEMO,
        open_price=115000.0,
        volume=0.02,
        initial_volume=0.02,
        profit=PROFIT_FLOTTANT,
        r_multiple=-1.0,
    )


def deal(ticket: int, profit: float, swap: float = 0.0, commission: float = 0.0) -> DealInfo:
    return DealInfo(
        ticket=ticket,
        order=ticket,
        position_id=TICKET,
        symbol="BTCUSDm",
        volume=0.02,
        price=115000.0,
        profit=profit,
        commission=commission,
        swap=swap,
        entry=0,
        time=utcnow(),
    )


def deal_d_entree() -> DealInfo:
    """Le deal d'ouverture : profit nul, c'est normal."""
    return deal(1, 0.0)


async def test_un_zero_du_courtier_ne_remplace_pas_une_perte_reelle(session) -> None:
    """Le cas de la position 44 : -3,91 $ inscrits, pas 0,00."""
    trade = position()
    session.add(trade)
    await session.flush()

    broker = BrokerSansDealDeSortie([deal_d_entree()])
    fermes = await PositionManager(broker).sync_with_broker(session, ExecutionMode.MT5_DEMO)

    assert len(fermes) == 1
    assert fermes[0].realized_pnl == PROFIT_FLOTTANT


async def test_un_zero_reste_zero_quand_la_position_n_a_rien_gagne(session) -> None:
    """On ne fabrique pas un chiffre : sans flottant, zero est la mesure.

    Une position sortie exactement au point mort a bien un resultat nul, et ce
    zero-la doit survivre. Sans ce test, il suffirait d'ignorer tout zero pour
    faire passer le precedent.
    """
    trade = position()
    trade.profit = 0.0
    session.add(trade)
    await session.flush()

    broker = BrokerSansDealDeSortie([deal_d_entree()])
    fermes = await PositionManager(broker).sync_with_broker(session, ExecutionMode.MT5_DEMO)

    assert len(fermes) == 1
    assert fermes[0].realized_pnl == 0.0


async def test_le_courtier_prime_quand_il_a_repondu(session) -> None:
    """Le deal de sortie publie l'emporte sur le flottant, qui est un repli."""
    trade = position()
    session.add(trade)
    await session.flush()

    sortie = deal(2, profit=-4.20, swap=-0.05, commission=-0.10)
    broker = BrokerSansDealDeSortie([deal_d_entree(), sortie])

    fermes = await PositionManager(broker).sync_with_broker(session, ExecutionMode.MT5_DEMO)

    assert fermes[0].realized_pnl == -4.35
