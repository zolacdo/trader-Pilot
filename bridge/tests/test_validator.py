"""Validateur strict : derniere barriere avant le RiskManager.

Aucun signal incoherent ne doit franchir cette couche, qu'il vienne du parser
local ou d'un modele de langage (CDC sections 21 et 49).
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction, OrderType, ParserSource
from app.services.signals.models import ParsedSignal
from app.services.signals.validator import (
    MAX_STOP_DISTANCE_RATIO,
    sanitize,
    validate,
)


def build(**kwargs: object) -> ParsedSignal:
    """Signal d'achat XAUUSD coherent, que chaque test degrade a sa facon."""
    base: dict[str, object] = {
        "is_signal": True,
        "symbol_raw": "GOLD",
        "symbol": "XAUUSD",
        "direction": Direction.BUY,
        "order_type": OrderType.MARKET,
        "entry_price": 3320.0,
        "stop_loss": 3310.0,
        "take_profits": [3340.0],
        "confidence": 0.95,
    }
    base.update(kwargs)
    return ParsedSignal(**base)  # type: ignore[arg-type]


def codes(signal: ParsedSignal) -> set[str]:
    return {issue.code for issue in validate(signal).issues}


# ---------------------------------------------------------------------------
# Cas nominal
# ---------------------------------------------------------------------------

def test_un_signal_coherent_est_accepte() -> None:
    result = validate(build())
    assert result.ok is True
    assert result.issues == []
    assert result.first_blocking is None


def test_un_message_sans_intention_est_refuse() -> None:
    result = validate(ParsedSignal(is_signal=False))
    assert result.ok is False
    assert result.first_blocking is not None
    assert result.first_blocking.code == "NO_ACTION"


def test_instrument_ou_direction_manquants() -> None:
    assert "SYMBOL_MISSING" in codes(build(symbol=None))
    assert "DIRECTION_MISSING" in codes(build(direction=None))


# ---------------------------------------------------------------------------
# Stop loss
# ---------------------------------------------------------------------------

def test_stop_loss_du_mauvais_cote_sur_un_achat() -> None:
    result = validate(build(stop_loss=3330.0, take_profits=[3400.0]))
    assert result.ok is False
    assert "SL_WRONG_SIDE" in {issue.code for issue in result.issues}


def test_stop_loss_du_mauvais_cote_sur_une_vente() -> None:
    signal = build(direction=Direction.SELL, stop_loss=3310.0, take_profits=[3300.0])
    result = validate(signal)
    assert result.ok is False
    assert "SL_WRONG_SIDE" in {issue.code for issue in result.issues}


def test_stop_loss_trop_loin_est_probablement_mal_lu() -> None:
    trop_loin = 3320.0 * (1 - MAX_STOP_DISTANCE_RATIO) - 1.0
    assert "SL_TOO_FAR" in codes(build(stop_loss=trop_loin))


def test_stop_loss_confondu_avec_l_entree() -> None:
    assert "SL_TOO_CLOSE" in codes(build(stop_loss=3320.0 - 1e-9))


def test_stop_loss_negatif() -> None:
    assert "NEGATIVE_VALUE" in codes(build(stop_loss=-3310.0))


# ---------------------------------------------------------------------------
# Take profits
# ---------------------------------------------------------------------------

def test_take_profit_du_mauvais_cote_sur_un_achat() -> None:
    assert "TP_WRONG_SIDE" in codes(build(take_profits=[3300.0]))


def test_take_profit_du_mauvais_cote_sur_une_vente() -> None:
    signal = build(direction=Direction.SELL, stop_loss=3330.0, take_profits=[3350.0])
    assert "TP_WRONG_SIDE" in codes(signal)


def test_take_profit_negatif() -> None:
    assert "NEGATIVE_VALUE" in codes(build(take_profits=[-3340.0]))


def test_take_profits_mal_ordonnes_sont_signales_sans_bloquer() -> None:
    result = validate(build(take_profits=[3360.0, 3340.0]))
    issues = {issue.code: issue for issue in result.issues}
    assert "TP_ORDER" in issues
    assert issues["TP_ORDER"].blocking is False
    assert result.ok is True


def test_doublon_de_take_profit_signale_sans_bloquer() -> None:
    result = validate(build(take_profits=[3340.0, 3340.0]))
    issues = {issue.code: issue for issue in result.issues}
    assert "TP_DUPLICATE" in issues
    assert issues["TP_DUPLICATE"].blocking is False
    assert result.ok is True


# ---------------------------------------------------------------------------
# Zone d'entree
# ---------------------------------------------------------------------------

def test_zone_d_entree_inversee_est_bloquante() -> None:
    signal = build(entry_price=None, entry_min=3320.0, entry_max=3315.0)
    assert "ENTRY_RANGE_INVERTED" in codes(signal)


def test_entree_negative() -> None:
    assert "NEGATIVE_VALUE" in codes(build(entry_price=-3320.0))


# ---------------------------------------------------------------------------
# Type d'ordre
# ---------------------------------------------------------------------------

def test_ordre_en_attente_sans_prix() -> None:
    signal = build(order_type=OrderType.BUY_LIMIT, entry_price=None)
    assert "PENDING_WITHOUT_PRICE" in codes(signal)


@pytest.mark.parametrize(
    ("order_type", "direction"),
    [
        (OrderType.BUY_LIMIT, Direction.SELL),
        (OrderType.BUY_STOP, Direction.SELL),
        (OrderType.SELL_LIMIT, Direction.BUY),
        (OrderType.SELL_STOP, Direction.BUY),
    ],
)
def test_type_d_ordre_incoherent_avec_la_direction(
    order_type: OrderType, direction: Direction
) -> None:
    stop_loss = 3310.0 if direction is Direction.BUY else 3330.0
    take_profit = 3340.0 if direction is Direction.BUY else 3300.0
    signal = build(
        order_type=order_type,
        direction=direction,
        stop_loss=stop_loss,
        take_profits=[take_profit],
    )
    assert "ORDER_TYPE_MISMATCH" in codes(signal)


def test_ordre_au_marche_sans_prix_reste_valide() -> None:
    signal = build(order_type=OrderType.MARKET, entry_price=None, take_profits=[])
    assert validate(signal).ok is True


# ---------------------------------------------------------------------------
# sanitize : nettoyages non destructifs
# ---------------------------------------------------------------------------

def test_sanitize_remet_la_zone_d_entree_dans_l_ordre() -> None:
    signal = sanitize(build(entry_price=None, entry_min=3320.0, entry_max=3315.0))
    assert signal.entry_min == 3315.0
    assert signal.entry_max == 3320.0
    assert "zone_entree_reordonnee" in signal.warnings
    assert validate(signal).ok is True


def test_sanitize_dedoublonne_et_trie_les_tp_d_un_achat() -> None:
    signal = sanitize(build(take_profits=[3360.0, 3340.0, 3340.0, 3350.0]))
    assert signal.take_profits == [3340.0, 3350.0, 3360.0]
    assert "take_profits_dedupliques" in signal.warnings


def test_sanitize_trie_les_tp_d_une_vente_en_decroissant() -> None:
    signal = sanitize(
        build(direction=Direction.SELL, stop_loss=3330.0, take_profits=[3300.0, 3320.0, 3310.0])
    )
    assert signal.take_profits == [3320.0, 3310.0, 3300.0]


def test_sanitize_ne_change_rien_a_un_signal_deja_propre() -> None:
    signal = sanitize(build())
    assert signal.warnings == []
    assert signal.take_profits == [3340.0]


def test_sanitize_n_invente_aucune_valeur() -> None:
    signal = sanitize(build(stop_loss=None, take_profits=[], entry_price=None))
    assert signal.stop_loss is None
    assert signal.take_profits == []
    assert signal.entry_price is None


# ---------------------------------------------------------------------------
# Une sortie d'IA passe par exactement les memes controles
# ---------------------------------------------------------------------------

def test_une_sortie_d_ia_incoherente_est_bloquee_comme_les_autres() -> None:
    signal = build(source=ParserSource.AI, ai_model="fake/model:free", stop_loss=3330.0)
    result = validate(signal)
    assert result.ok is False
    assert "SL_WRONG_SIDE" in {issue.code for issue in result.issues}


def test_to_dict_du_resultat_de_validation() -> None:
    payload = validate(build(stop_loss=3330.0)).to_dict()
    assert payload["ok"] is False
    assert any(issue["code"] == "SL_WRONG_SIDE" for issue in payload["issues"])
