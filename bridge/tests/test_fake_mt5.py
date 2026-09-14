"""Simulateur MetaTrader 5 : le banc d'essai de tout le reste.

Aucun appel au paquet ``MetaTrader5``, aucun terminal, aucune cotation reelle.
Les prix et les bougies sont SYNTHETIQUES et parfaitement deterministes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import AccountKind, Direction, OrderType
from app.services.mt5.fake_service import FIRST_TICKET, FakeMetaTraderService
from app.services.mt5.interface import OrderRequest

# Prix de base du catalogue simule : XAUUSD bid 3350.00, spread 20 points.
BID = 3350.0
ASK = 3350.20


@pytest.fixture
async def mt5() -> FakeMetaTraderService:
    service = FakeMetaTraderService(balance=10000.0)
    await service.initialize()
    return service


def market_buy(volume: float = 0.10, **kwargs: object) -> OrderRequest:
    request = OrderRequest(
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=OrderType.MARKET,
        volume=volume,
        magic=1,
        comment="test",
    )
    for key, value in kwargs.items():
        setattr(request, key, value)
    return request


# ---------------------------------------------------------------------------
# Cycle de vie et lecture
# ---------------------------------------------------------------------------

async def test_initialisation_et_arret(mt5: FakeMetaTraderService) -> None:
    assert await mt5.is_connected() is True
    terminal = await mt5.terminal_info()
    assert terminal is not None and terminal.connected is True
    await mt5.shutdown()
    assert await mt5.is_connected() is False


async def test_compte_simule_est_toujours_demo(mt5: FakeMetaTraderService) -> None:
    account = await mt5.account_info()
    assert account is not None
    assert account.kind is AccountKind.DEMO
    assert account.balance == pytest.approx(10000.0)
    assert account.equity == pytest.approx(10000.0)
    assert account.trade_allowed is True


async def test_catalogue_de_symboles(mt5: FakeMetaTraderService) -> None:
    names = await mt5.symbols()
    assert "XAUUSD" in names and "EURUSD" in names and "US30" in names
    assert names == sorted(names)
    assert await mt5.ensure_symbol("XAUUSD") is True
    assert await mt5.ensure_symbol("INCONNU") is False
    assert await mt5.symbol_info("INCONNU") is None
    assert await mt5.symbol_tick("INCONNU") is None


async def test_cotation(mt5: FakeMetaTraderService) -> None:
    tick = await mt5.symbol_tick("XAUUSD")
    info = await mt5.symbol_info("XAUUSD")
    assert tick is not None and info is not None
    assert tick.bid == pytest.approx(BID)
    assert tick.ask == pytest.approx(ASK)
    assert tick.spread_points(info.point) == 20


# ---------------------------------------------------------------------------
# Ouverture et fermeture
# ---------------------------------------------------------------------------

async def test_ouverture_de_position(mt5: FakeMetaTraderService) -> None:
    result = await mt5.order_send(market_buy(0.10, stop_loss=3340.0, take_profit=3370.0))

    assert result.ok is True
    assert result.retcode == 10009
    assert result.position == FIRST_TICKET
    assert result.price == pytest.approx(ASK)

    positions = await mt5.positions()
    assert len(positions) == 1
    position = positions[0]
    assert position.symbol == "XAUUSD"
    assert position.direction is Direction.BUY
    assert position.volume == pytest.approx(0.10)
    assert position.stop_loss == pytest.approx(3340.0)
    assert position.take_profit == pytest.approx(3370.0)
    # Achat ouvert au ask et valorise au bid : la perte de depart est le spread.
    assert position.profit == pytest.approx(-2.0)


async def test_fermeture_totale_credite_le_resultat(mt5: FakeMetaTraderService) -> None:
    await mt5.order_send(market_buy(0.10))
    mt5.set_price("XAUUSD", 3360.0)

    result = await mt5.close_position(FIRST_TICKET)

    assert result.ok is True
    # (3360.00 - 3350.20) * 0.10 * 100 = 98.00
    assert result.price == pytest.approx(3360.0)
    assert mt5.balance == pytest.approx(10098.0)
    assert await mt5.positions() == []


async def test_fermeture_partielle(mt5: FakeMetaTraderService) -> None:
    await mt5.order_send(market_buy(0.10))
    mt5.set_price("XAUUSD", 3360.0)

    result = await mt5.close_position(FIRST_TICKET, volume=0.04)

    assert result.ok is True
    assert result.volume == pytest.approx(0.04)
    positions = await mt5.positions()
    assert len(positions) == 1
    assert positions[0].volume == pytest.approx(0.06)
    # (3360.00 - 3350.20) * 0.04 * 100 = 39.20
    assert mt5.balance == pytest.approx(10039.20)


async def test_fermeture_d_une_position_inconnue(mt5: FakeMetaTraderService) -> None:
    result = await mt5.close_position(123456)
    assert result.ok is False
    assert result.retcode == 10013


async def test_modification_des_stops(mt5: FakeMetaTraderService) -> None:
    await mt5.order_send(market_buy(0.10, stop_loss=3340.0, take_profit=3370.0))
    result = await mt5.modify_position(FIRST_TICKET, 3345.0, 3380.0)
    assert result.ok is True
    position = (await mt5.positions())[0]
    assert position.stop_loss == pytest.approx(3345.0)
    assert position.take_profit == pytest.approx(3380.0)

    assert (await mt5.modify_position(999, 1.0, 2.0)).ok is False


# ---------------------------------------------------------------------------
# Declenchement SL / TP par la simulation
# ---------------------------------------------------------------------------

async def test_tick_declenche_le_stop_loss(mt5: FakeMetaTraderService) -> None:
    await mt5.order_send(market_buy(0.10, stop_loss=3340.0, take_profit=3370.0))
    mt5.set_price("XAUUSD", 3339.0)

    events = mt5.tick()

    assert events == [{"type": "sl_hit", "ticket": FIRST_TICKET, "price": 3340.0}]
    assert await mt5.positions() == []
    # (3340.00 - 3350.20) * 0.10 * 100 = -102.00
    assert mt5.balance == pytest.approx(9898.0)


async def test_tick_declenche_le_take_profit(mt5: FakeMetaTraderService) -> None:
    await mt5.order_send(market_buy(0.10, stop_loss=3340.0, take_profit=3370.0))
    mt5.set_price("XAUUSD", 3371.0)

    events = mt5.tick()

    assert events == [{"type": "tp_hit", "ticket": FIRST_TICKET, "price": 3370.0}]
    assert await mt5.positions() == []
    # (3370.00 - 3350.20) * 0.10 * 100 = 198.00
    assert mt5.balance == pytest.approx(10198.0)


async def test_tick_declenche_le_stop_loss_d_une_vente(mt5: FakeMetaTraderService) -> None:
    request = market_buy(0.10, stop_loss=3365.0, take_profit=3330.0)
    request.direction = Direction.SELL
    await mt5.order_send(request)
    mt5.set_price("XAUUSD", 3370.0)

    events = mt5.tick()

    assert events and events[0]["type"] == "sl_hit"
    assert mt5.balance < 10000.0


async def test_tick_sans_mouvement_ne_produit_rien(mt5: FakeMetaTraderService) -> None:
    await mt5.order_send(market_buy(0.10, stop_loss=3340.0, take_profit=3370.0))
    assert mt5.tick() == []
    assert len(await mt5.positions()) == 1


# ---------------------------------------------------------------------------
# Ordres en attente
# ---------------------------------------------------------------------------

async def test_ordre_en_attente_place_puis_rempli(mt5: FakeMetaTraderService) -> None:
    request = market_buy(0.10, stop_loss=3320.0, take_profit=3380.0)
    request.order_type = OrderType.BUY_LIMIT
    request.price = 3340.0

    result = await mt5.order_send(request)
    assert result.ok is True
    assert result.retcode == 10008
    assert result.order == FIRST_TICKET
    assert len(await mt5.orders()) == 1
    assert await mt5.positions() == []

    # Le ask doit descendre a 3340 : bid 3339.80 + 20 points.
    mt5.set_price("XAUUSD", 3339.80)
    events = mt5.tick()

    assert events == [{"type": "pending_filled", "ticket": FIRST_TICKET, "price": 3340.0}]
    assert await mt5.orders() == []
    positions = await mt5.positions()
    assert len(positions) == 1
    assert positions[0].price_open == pytest.approx(3340.0)


async def test_annulation_d_un_ordre_en_attente(mt5: FakeMetaTraderService) -> None:
    request = market_buy(0.10)
    request.order_type = OrderType.SELL_LIMIT
    request.price = 3400.0
    await mt5.order_send(request)

    assert (await mt5.cancel_order(FIRST_TICKET)).ok is True
    assert await mt5.orders() == []
    assert (await mt5.cancel_order(FIRST_TICKET)).ok is False


async def test_modification_d_un_ordre_en_attente(mt5: FakeMetaTraderService) -> None:
    request = market_buy(0.10)
    request.order_type = OrderType.BUY_LIMIT
    request.price = 3340.0
    await mt5.order_send(request)

    result = await mt5.modify_order(FIRST_TICKET, 3335.0, 3320.0, 3380.0)
    assert result.ok is True
    order = (await mt5.orders())[0]
    assert order.price_open == pytest.approx(3335.0)
    assert order.stop_loss == pytest.approx(3320.0)

    assert (await mt5.modify_order(999, None, None, None)).ok is False


# ---------------------------------------------------------------------------
# order_check : le broker refuse avant l'envoi
# ---------------------------------------------------------------------------

async def test_order_check_accepte_une_requete_valide(mt5: FakeMetaTraderService) -> None:
    result = await mt5.order_check(market_buy(0.10, stop_loss=3340.0, take_profit=3370.0))
    assert result.ok is True
    assert result.price == pytest.approx(ASK)


@pytest.mark.parametrize(
    ("volume", "retcode"),
    [
        (0.001, 10014),  # sous le minimum
        (60.0, 10014),  # au-dessus du maximum
        (0.015, 10014),  # pas un multiple du pas de 0.01
    ],
)
async def test_order_check_refuse_un_volume_invalide(
    mt5: FakeMetaTraderService, volume: float, retcode: int
) -> None:
    result = await mt5.order_check(market_buy(volume))
    assert result.ok is False
    assert result.retcode == retcode


async def test_order_check_refuse_un_stop_loss_du_mauvais_cote(
    mt5: FakeMetaTraderService,
) -> None:
    result = await mt5.order_check(market_buy(0.10, stop_loss=3360.0))
    assert result.ok is False
    assert result.retcode == 10016
    assert "sous le prix" in result.message


async def test_order_check_refuse_un_stop_loss_trop_proche(mt5: FakeMetaTraderService) -> None:
    """Le broker simule exige 20 points, soit 0.20 dollar sur XAUUSD."""
    result = await mt5.order_check(market_buy(0.10, stop_loss=3350.10))
    assert result.ok is False
    assert result.retcode == 10016
    assert "trop proche" in result.message


async def test_order_check_refuse_un_take_profit_du_mauvais_cote(
    mt5: FakeMetaTraderService,
) -> None:
    result = await mt5.order_check(market_buy(0.10, take_profit=3340.0))
    assert result.ok is False
    assert result.retcode == 10016


async def test_order_check_refuse_une_marge_insuffisante(mt5: FakeMetaTraderService) -> None:
    """50 lots XAUUSD a 3350 : 33 500 USD de marge pour 10 000 disponibles."""
    result = await mt5.order_check(market_buy(50.0))
    assert result.ok is False
    assert result.retcode == 10019
    assert "Marge insuffisante" in result.message


async def test_order_check_refuse_un_ordre_en_attente_sans_prix(
    mt5: FakeMetaTraderService,
) -> None:
    request = market_buy(0.10)
    request.order_type = OrderType.BUY_LIMIT
    request.price = None
    result = await mt5.order_check(request)
    assert result.ok is False
    assert result.retcode == 10015


async def test_order_check_refuse_un_symbole_inconnu(mt5: FakeMetaTraderService) -> None:
    request = market_buy(0.10)
    request.symbol = "INCONNU"
    result = await mt5.order_check(request)
    assert result.ok is False
    assert result.retcode == 10013


async def test_order_send_refuse_ce_que_order_check_refuse(mt5: FakeMetaTraderService) -> None:
    result = await mt5.order_send(market_buy(0.10, stop_loss=3360.0))
    assert result.ok is False
    assert await mt5.positions() == []


# ---------------------------------------------------------------------------
# Calculs
# ---------------------------------------------------------------------------

async def test_calculate_profit(mt5: FakeMetaTraderService) -> None:
    # 1 lot XAUUSD = 100 onces : 10 dollars de mouvement = 1000 USD.
    gain = await mt5.calculate_profit("XAUUSD", Direction.BUY, 1.0, 3320.0, 3330.0)
    perte = await mt5.calculate_profit("XAUUSD", Direction.BUY, 1.0, 3320.0, 3310.0)
    vente = await mt5.calculate_profit("XAUUSD", Direction.SELL, 1.0, 3320.0, 3310.0)
    assert gain == pytest.approx(1000.0)
    assert perte == pytest.approx(-1000.0)
    assert vente == pytest.approx(1000.0)
    assert await mt5.calculate_profit("INCONNU", Direction.BUY, 1.0, 1.0, 2.0) is None


async def test_calculate_profit_eurusd(mt5: FakeMetaTraderService) -> None:
    # 1 lot EURUSD = 100 000 euros : 30 pips = 300 USD.
    profit = await mt5.calculate_profit("EURUSD", Direction.BUY, 1.0, 1.0820, 1.0850)
    assert profit == pytest.approx(300.0)


async def test_calculate_margin(mt5: FakeMetaTraderService) -> None:
    # 0.10 * 100 onces * 3350 / levier 500 = 67.00 USD
    margin = await mt5.calculate_margin("XAUUSD", Direction.BUY, 0.10, 3350.0)
    assert margin == pytest.approx(67.0)
    assert await mt5.calculate_margin("INCONNU", Direction.BUY, 1.0, 1.0) is None


async def test_marge_utilisee_et_marge_libre(mt5: FakeMetaTraderService) -> None:
    await mt5.order_send(market_buy(0.10))
    account = await mt5.account_info()
    assert account is not None
    assert account.margin == pytest.approx(67.0, abs=0.5)
    assert account.margin_free == pytest.approx(account.equity - account.margin)


# ---------------------------------------------------------------------------
# Historique et bougies
# ---------------------------------------------------------------------------

async def test_historique_des_deals(mt5: FakeMetaTraderService) -> None:
    await mt5.order_send(market_buy(0.10))
    mt5.set_price("XAUUSD", 3360.0)
    await mt5.close_position(FIRST_TICKET)

    deals = await mt5.history_deals(datetime.now(tz=UTC) - timedelta(hours=1))
    assert len(deals) == 2
    entree, sortie = deals
    assert entree.entry == 0
    assert sortie.entry == 1
    assert sortie.profit == pytest.approx(98.0)
    assert sortie.position_id == FIRST_TICKET


async def test_bougies_deterministes(mt5: FakeMetaTraderService) -> None:
    start = datetime(2025, 3, 3, 8, 0, tzinfo=UTC)
    end = start + timedelta(hours=6)

    first = await mt5.candles("XAUUSD", "M15", start, end)
    second = await mt5.candles("XAUUSD", "M15", start, end)

    assert len(first) > 10
    assert [candle.to_dict() for candle in first] == [candle.to_dict() for candle in second]
    for candle in first:
        assert candle.low <= candle.open <= candle.high
        assert candle.low <= candle.close <= candle.high
        assert candle.tick_volume > 0


async def test_bougies_differentes_selon_le_symbole(mt5: FakeMetaTraderService) -> None:
    start = datetime(2025, 3, 3, 8, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    gold = await mt5.candles("XAUUSD", "M15", start, end)
    eurusd = await mt5.candles("EURUSD", "M15", start, end)
    assert gold and eurusd
    assert gold[0].close != eurusd[0].close


async def test_bougies_cas_limites(mt5: FakeMetaTraderService) -> None:
    start = datetime(2025, 3, 3, 8, 0, tzinfo=UTC)
    assert await mt5.candles("INCONNU", "M15", start, start + timedelta(hours=1)) == []
    assert await mt5.candles("XAUUSD", "INCONNU", start, start + timedelta(hours=1)) == []
    assert await mt5.candles("XAUUSD", "M15", start, start) == []


# ---------------------------------------------------------------------------
# Pilotage du simulateur
# ---------------------------------------------------------------------------

async def test_reset_remet_tout_a_zero(mt5: FakeMetaTraderService) -> None:
    await mt5.order_send(market_buy(0.10))
    mt5.set_price("XAUUSD", 3400.0)

    mt5.reset()

    assert await mt5.positions() == []
    assert mt5.balance == pytest.approx(10000.0)
    tick = await mt5.symbol_tick("XAUUSD")
    assert tick is not None and tick.bid == pytest.approx(BID)


async def test_move_price_et_symbole_inconnu(mt5: FakeMetaTraderService) -> None:
    mt5.move_price("XAUUSD", 5.0)
    tick = await mt5.symbol_tick("XAUUSD")
    assert tick is not None and tick.bid == pytest.approx(BID + 5.0)
    with pytest.raises(KeyError):
        mt5.set_price("INCONNU", 1.0)
