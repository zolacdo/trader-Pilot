"""Calcul du volume : la perte au stop doit valoir le risque demande.

Toutes les valeurs attendues sont recalculees a la main dans les commentaires :
c'est le coeur du dimensionnement, il ne doit jamais deriver silencieusement.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction
from app.services.mt5.interface import SymbolInfo
from app.services.risk.calculator import (
    calculate_lot,
    clamp_to_stops_level,
    loss_for_one_lot,
    normalize_price,
    points_between,
    respects_stops_level,
    round_to_step,
    split_volume,
)
from app.services.trading.paper import PaperTradingService

BALANCE = 10000.0


# ---------------------------------------------------------------------------
# round_to_step
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("volume", "step", "expected"),
    [
        (0.127, 0.01, 0.12),
        (0.1, 0.01, 0.10),
        (0.049, 0.01, 0.04),
        (0.1279, 0.001, 0.127),
        (1.2345, 0.001, 1.234),
        (0.55, 0.1, 0.5),
        (2.0, 0.1, 2.0),
        (0.009, 0.01, 0.0),
    ],
)
def test_round_to_step_arrondit_toujours_vers_le_bas(
    volume: float, step: float, expected: float
) -> None:
    assert round_to_step(volume, step) == pytest.approx(expected)


def test_round_to_step_sans_pas_valide() -> None:
    assert round_to_step(0.126, 0.0) == 0.13


# ---------------------------------------------------------------------------
# points_between
# ---------------------------------------------------------------------------

async def test_points_between(paper: PaperTradingService) -> None:
    gold = await paper.symbol_info("XAUUSD")
    eurusd = await paper.symbol_info("EURUSD")
    us30 = await paper.symbol_info("US30")
    assert gold is not None and eurusd is not None and us30 is not None

    # XAUUSD : point 0.01 -> 10 dollars = 1000 points
    assert points_between(3320.0, 3310.0, gold) == 1000
    # EURUSD : point 0.00001 -> 30 pips = 300 points
    assert points_between(1.0820, 1.0790, eurusd) == 300
    # US30 : point 0.1 -> 150 indices = 1500 points
    assert points_between(44400.0, 44250.0, us30) == 1500
    # La mesure est symetrique et absolue
    assert points_between(3310.0, 3320.0, gold) == 1000


def test_points_between_sans_point_valide() -> None:
    broken = SymbolInfo(name="BROKEN", point=0.0)
    assert points_between(10.0, 9.0, broken) == 0


# ---------------------------------------------------------------------------
# calculate_lot : verification manuelle de la perte au stop
# ---------------------------------------------------------------------------

async def test_calculate_lot_xauusd_risque_un_pour_cent(paper: PaperTradingService) -> None:
    """1 lot XAUUSD = 100 onces : 10 dollars de stop = 1000 USD par lot.

    Risque 1 % de 10 000 = 100 USD -> 100 / 1000 = 0.10 lot exactement.
    """
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None

    result = await calculate_lot(
        service=paper,
        symbol=gold,
        direction=Direction.BUY,
        entry=3320.0,
        stop_loss=3310.0,
        balance=BALANCE,
        risk_percent=1.0,
    )

    assert result.ok is True
    assert result.volume == pytest.approx(0.10)
    assert result.risk_amount == pytest.approx(100.0)
    assert result.loss_per_lot == pytest.approx(1000.0)
    assert result.loss_at_stop == pytest.approx(100.0)
    assert result.stop_distance == pytest.approx(10.0)
    assert result.stop_distance_points == 1000
    # La perte au stop vaut bien le pourcentage demande.
    assert result.loss_at_stop / BALANCE * 100 == pytest.approx(1.0)


async def test_calculate_lot_eurusd_risque_un_pour_cent(paper: PaperTradingService) -> None:
    """1 lot EURUSD = 100 000 euros : 30 pips = 300 USD par lot.

    Risque 1 % de 10 000 = 100 USD -> 0.3333 lot, arrondi vers le bas a 0.33,
    soit 99 USD de perte au stop (jamais plus que le risque demande).
    """
    eurusd = await paper.symbol_info("EURUSD")
    assert eurusd is not None

    result = await calculate_lot(
        service=paper,
        symbol=eurusd,
        direction=Direction.BUY,
        entry=1.0820,
        stop_loss=1.0790,
        balance=BALANCE,
        risk_percent=1.0,
    )

    assert result.ok is True
    assert result.volume == pytest.approx(0.33)
    assert result.loss_per_lot == pytest.approx(300.0)
    assert result.loss_at_stop == pytest.approx(99.0)
    assert result.loss_at_stop <= result.risk_amount


async def test_calculate_lot_us30_vente(paper: PaperTradingService) -> None:
    """US30 : contrat 1 -> 150 points d'indice = 150 USD par lot.

    Risque 3 % de 10 000 = 300 USD -> 2.00 lots, perte au stop 300 USD.
    """
    us30 = await paper.symbol_info("US30")
    assert us30 is not None

    result = await calculate_lot(
        service=paper,
        symbol=us30,
        direction=Direction.SELL,
        entry=44250.0,
        stop_loss=44400.0,
        balance=BALANCE,
        risk_percent=3.0,
    )

    assert result.ok is True
    assert result.volume == pytest.approx(2.0)
    assert result.loss_per_lot == pytest.approx(150.0)
    assert result.loss_at_stop == pytest.approx(300.0)
    assert result.loss_at_stop / BALANCE * 100 == pytest.approx(3.0)


async def test_calculate_lot_refuse_sous_le_volume_minimum(paper: PaperTradingService) -> None:
    """0.05 % de 10 000 = 5 USD : 0.005 lot, sous le minimum broker de 0.01."""
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None

    result = await calculate_lot(
        service=paper,
        symbol=gold,
        direction=Direction.BUY,
        entry=3320.0,
        stop_loss=3310.0,
        balance=BALANCE,
        risk_percent=0.05,
    )

    assert result.ok is False
    assert result.volume is None
    assert result.reason is not None
    assert "minimum broker" in result.reason
    assert result.details["volumeMin"] == 0.01


async def test_calculate_lot_plafonne_par_max_lot(paper: PaperTradingService) -> None:
    """5 % donnerait 0.50 lot : le plafond utilisateur de 0.10 s'applique."""
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None

    result = await calculate_lot(
        service=paper,
        symbol=gold,
        direction=Direction.BUY,
        entry=3320.0,
        stop_loss=3310.0,
        balance=BALANCE,
        risk_percent=5.0,
        max_lot=0.10,
    )

    assert result.ok is True
    assert result.volume == pytest.approx(0.10)
    assert result.details["cappedByLimit"] is True
    assert result.details["requestedVolume"] == pytest.approx(0.5)
    # Le plafond protege : la perte reelle est inferieure au risque demande.
    assert result.loss_at_stop == pytest.approx(100.0)


async def test_calculate_lot_plafonne_par_le_volume_max_du_broker(
    paper: PaperTradingService,
) -> None:
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None

    result = await calculate_lot(
        service=paper,
        symbol=gold,
        direction=Direction.BUY,
        entry=3320.0,
        stop_loss=3319.99,
        balance=100_000_000.0,
        risk_percent=10.0,
    )

    assert result.ok is True
    assert result.volume == pytest.approx(gold.volume_max)
    assert result.details["cappedByLimit"] is True


@pytest.mark.parametrize(
    ("entry", "stop_loss", "balance", "risk", "fragment"),
    [
        (0.0, 3310.0, BALANCE, 1.0, "invalide"),
        (3320.0, 0.0, BALANCE, 1.0, "invalide"),
        (3320.0, 3320.0, BALANCE, 1.0, "confondu"),
        (3320.0, 3310.0, 0.0, 1.0, "Solde"),
        (3320.0, 3310.0, BALANCE, 0.0, "risque nul"),
    ],
)
async def test_calculate_lot_refuse_les_entrees_invalides(
    paper: PaperTradingService,
    entry: float,
    stop_loss: float,
    balance: float,
    risk: float,
    fragment: str,
) -> None:
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None

    result = await calculate_lot(
        service=paper,
        symbol=gold,
        direction=Direction.BUY,
        entry=entry,
        stop_loss=stop_loss,
        balance=balance,
        risk_percent=risk,
    )
    assert result.ok is False
    assert result.reason is not None
    assert fragment in result.reason


async def test_calculate_lot_sur_symbole_inconnu_du_terminal(
    paper: PaperTradingService,
) -> None:
    """Sans valorisation possible, aucun volume n'est invente."""
    inconnu = SymbolInfo(
        name="UNKNOWNPAIR",
        digits=2,
        point=0.01,
        trade_tick_size=0.0,
        trade_tick_value=0.0,
        trade_contract_size=0.0,
    )
    result = await calculate_lot(
        service=paper,
        symbol=inconnu,
        direction=Direction.BUY,
        entry=100.0,
        stop_loss=99.0,
        balance=BALANCE,
        risk_percent=1.0,
    )
    assert result.ok is False
    assert result.volume is None
    assert result.method == "unavailable"


async def test_loss_for_one_lot_retombe_sur_la_valeur_du_tick(
    paper: PaperTradingService,
) -> None:
    """Symbole absent du terminal : calcul par tick_value / tick_size."""
    hors_catalogue = SymbolInfo(
        name="HORSCATALOGUE",
        digits=2,
        point=0.01,
        trade_tick_size=0.01,
        trade_tick_value=1.0,
        trade_contract_size=100.0,
    )
    loss, method = await loss_for_one_lot(
        paper, hors_catalogue, Direction.BUY, 3320.0, 3310.0
    )
    assert method == "tick_value"
    assert loss == pytest.approx(1000.0)


async def test_loss_for_one_lot_utilise_le_terminal_quand_il_repond(
    paper: PaperTradingService,
) -> None:
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None
    loss, method = await loss_for_one_lot(paper, gold, Direction.SELL, 3320.0, 3330.0)
    assert method == "order_calc_profit"
    assert loss == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# split_volume
# ---------------------------------------------------------------------------

async def test_split_volume_reparti_40_30_30(paper: PaperTradingService) -> None:
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None
    parts = split_volume(1.0, [40.0, 30.0, 30.0], gold)
    assert parts == [0.4, 0.3, 0.3]
    assert sum(parts) == pytest.approx(1.0)


async def test_split_volume_reaffecte_le_reste_a_la_premiere_position(
    paper: PaperTradingService,
) -> None:
    """0.05 lot en 40/30/30 : 0.02 + 0.01 + 0.01, le residu va sur la premiere."""
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None
    parts = split_volume(0.05, [40.0, 30.0, 30.0], gold)
    assert sum(parts) == pytest.approx(0.05)
    assert parts[0] >= parts[1]
    assert all(part >= gold.volume_min for part in parts)


async def test_split_volume_impossible_retourne_une_liste_vide(
    paper: PaperTradingService,
) -> None:
    """0.02 lot en trois parts donnerait 0.008 : sous le minimum broker."""
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None
    assert split_volume(0.02, [40.0, 30.0, 30.0], gold) == []
    assert split_volume(0.0, [40.0, 30.0, 30.0], gold) == []
    assert split_volume(1.0, [], gold) == []
    assert split_volume(1.0, [0.0, 0.0], gold) == []


# ---------------------------------------------------------------------------
# Contraintes de prix du broker
# ---------------------------------------------------------------------------

async def test_normalize_price(paper: PaperTradingService) -> None:
    gold = await paper.symbol_info("XAUUSD")
    eurusd = await paper.symbol_info("EURUSD")
    assert gold is not None and eurusd is not None
    assert normalize_price(3320.456, gold) == 3320.46
    assert normalize_price(1.0820456, eurusd) == 1.08205
    assert normalize_price(None, gold) is None


async def test_respects_stops_level(paper: PaperTradingService) -> None:
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None
    assert gold.trade_stops_level == 20
    assert respects_stops_level(3320.0, 3310.0, gold) is True
    # 10 points seulement : sous les 20 points exiges par le broker
    assert respects_stops_level(3320.0, 3319.90, gold) is False
    assert respects_stops_level(3320.0, 3319.90, gold, tolerance_points=-20) is True


async def test_clamp_to_stops_level(paper: PaperTradingService) -> None:
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None
    # 20 points = 0.20 dollar
    assert clamp_to_stops_level(3320.0, 3319.90, gold, is_above=False) == 3319.80
    assert clamp_to_stops_level(3320.0, 3320.10, gold, is_above=True) == 3320.20
    # Un stop deja assez eloigne n'est pas deplace
    assert clamp_to_stops_level(3320.0, 3310.0, gold, is_above=False) == 3310.0
