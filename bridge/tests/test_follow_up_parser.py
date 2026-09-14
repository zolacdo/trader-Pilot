"""Messages de suivi rattaches a un signal deja envoye (CDC section 18).

Le risque symetrique est double : rater un "CLOSE GOLD" laisserait une
position ouverte, mais lire un vrai signal d'entree comme un message de suivi
declencherait une action sur la mauvaise position.
"""

from __future__ import annotations

import pytest

from app.models.enums import FollowUpAction
from app.services.signals.deterministic_parser import parse
from app.services.signals.follow_up_parser import parse_follow_up
from tests.fixtures.messages import (
    CLEAN_SIGNALS,
    FOLLOW_UP_MESSAGES,
    NOISE_MESSAGES,
    FollowUpCase,
    SignalCase,
)


def _ids(cases: tuple) -> list[str]:
    return [case.label if hasattr(case, "label") else case[0] for case in cases]


@pytest.mark.parametrize("case", FOLLOW_UP_MESSAGES, ids=_ids(FOLLOW_UP_MESSAGES))
def test_messages_de_suivi_interpretes_champ_par_champ(case: FollowUpCase) -> None:
    follow_up = parse_follow_up(case.text)

    assert follow_up is not None, case.label
    assert follow_up.action is case.action
    assert follow_up.symbol == case.symbol
    assert follow_up.tp_index == case.tp_index
    assert follow_up.percentage == case.percentage
    assert follow_up.price == case.price
    assert follow_up.also_break_even is case.also_break_even
    assert 0.0 < follow_up.confidence <= 1.0


@pytest.mark.parametrize("case", FOLLOW_UP_MESSAGES, ids=_ids(FOLLOW_UP_MESSAGES))
def test_un_message_de_suivi_n_est_jamais_un_signal_d_entree(case: FollowUpCase) -> None:
    assert parse(case.text).is_signal is False, case.label


@pytest.mark.parametrize("case", CLEAN_SIGNALS, ids=_ids(CLEAN_SIGNALS))
def test_un_vrai_signal_n_est_jamais_vu_comme_un_message_de_suivi(case: SignalCase) -> None:
    """Un ordre d'entree ne doit surtout pas fermer ou modifier une position."""
    follow_up = parse_follow_up(case.text)
    if follow_up is not None:
        # Seul un signal contenant explicitement "CLOSE"/"CANCEL" pourrait
        # remonter ici : aucun de nos signaux propres n'est dans ce cas.
        pytest.fail(f"{case.label} interprete comme suivi : {follow_up.action}")


@pytest.mark.parametrize(("label", "text"), NOISE_MESSAGES, ids=_ids(NOISE_MESSAGES))
def test_le_bavardage_ne_produit_pas_d_action_de_suivi(label: str, text: str) -> None:
    follow_up = parse_follow_up(text)
    if follow_up is not None:
        assert follow_up.action is FollowUpAction.INFO, label


def test_message_vide_ou_blanc() -> None:
    assert parse_follow_up("") is None
    assert parse_follow_up("    \n  ") is None


def test_tp_hit_sans_index_vaut_tp1() -> None:
    follow_up = parse_follow_up("TP HIT")
    assert follow_up is not None
    assert follow_up.action is FollowUpAction.TP_HIT
    assert follow_up.tp_index == 1


def test_tp_hit_formule_a_l_envers() -> None:
    follow_up = parse_follow_up("HIT TP2 easy money")
    assert follow_up is not None
    assert follow_up.action is FollowUpAction.TP_HIT
    assert follow_up.tp_index == 2


def test_fermeture_totale_a_cent_pour_cent() -> None:
    follow_up = parse_follow_up("CLOSE 100% NOW")
    assert follow_up is not None
    assert follow_up.action is FollowUpAction.CLOSE_ALL


def test_fermeture_partielle_avec_instrument() -> None:
    follow_up = parse_follow_up("CLOSE 30% ON GOLD")
    assert follow_up is not None
    assert follow_up.action is FollowUpAction.CLOSE_PARTIAL
    assert follow_up.percentage == 30.0
    assert follow_up.symbol == "XAUUSD"


def test_nouveau_signal_dans_le_message_bloque_la_fermeture() -> None:
    """"CLOSE" accompagne d'un BUY/SELL : le message n'est pas une fermeture."""
    assert parse_follow_up("CLOSE THE SELL AND BUY XAUUSD 3320") is None


def test_move_sl_conserve_le_prix_exact() -> None:
    follow_up = parse_follow_up("MOVE SL TO 3312.50")
    assert follow_up is not None
    assert follow_up.action is FollowUpAction.MOVE_SL
    assert follow_up.price == 3312.50


def test_break_even_combine_avec_un_tp_hit() -> None:
    follow_up = parse_follow_up("TP1 HIT, MOVE SL TO BE NOW")
    assert follow_up is not None
    assert follow_up.action is FollowUpAction.TP_HIT
    assert follow_up.also_break_even is True


def test_les_alias_de_canal_sont_utilises_pour_le_suivi() -> None:
    follow_up = parse_follow_up("CLOSE ZEDAX NOW", {"ZEDAX": "GER40"})
    assert follow_up is not None
    assert follow_up.symbol == "GER40"


def test_to_dict_expose_les_champs_attendus() -> None:
    follow_up = parse_follow_up("CLOSE 50% GOLD")
    assert follow_up is not None
    payload = follow_up.to_dict()
    assert payload["action"] == FollowUpAction.CLOSE_PARTIAL.value
    assert payload["percentage"] == 50.0
    assert payload["symbol"] == "XAUUSD"
    assert payload["alsoBreakEven"] is False
