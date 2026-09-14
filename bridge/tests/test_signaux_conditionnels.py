"""Un signal conditionnel n'est pas un ordre au marche.

Message reellement recu le 12/09/2026 :

    BTCUSD - FUTUR PROBABLE
    Zone cle : 77335 - 77345
    Si cassure confirmee :
    BUY SCENARIO
    Entry 77345
    SL 77260

Lu tel quel, le systeme en faisait un achat IMMEDIAT : entree a ``None``, type
d'ordre a ``None``, donc au marche. Le Bitcoin cotait 77 200 et le stop demande
etait a 77 260, AU-DESSUS du prix. Ce n'etait pas le trade demande.

Deux defauts distincts, corriges ici :

  * « Zone cle » etait lue comme l'entree parce qu'elle apparait avant
    « Entry » et que les deux portent l'etiquette ZONE ;
  * la condition de cassure etait ignoree, alors qu'elle transforme l'ordre en
    ordre EN ATTENTE.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction, OrderType
from app.services.signals import deterministic_parser

MESSAGE_REEL = """BTCUSD — FUTUR PROBABLE

Biais : HAUSSIER PRUDENT

Zone clé : 77335 - 77345

Si cassure confirmée :

BUY SCENARIO
Entry 77345
SL 77260
TP1 77430
TP2 77515
TP3 77600

Invalidation :
Clôture nette sous 77260
→ risque de retour vers 77220 / 77190"""


def test_le_message_reel_devient_un_ordre_en_attente() -> None:
    """Le cas exact vu en production, de bout en bout."""
    lu = deterministic_parser.parse(MESSAGE_REEL)

    assert lu.is_signal is True
    assert lu.symbol == "BTCUSD"
    assert lu.direction is Direction.BUY
    assert lu.order_type is OrderType.BUY_STOP, (
        "une cassure annoncee doit poser un ordre en attente, pas acheter maintenant"
    )
    assert lu.entry_price == 77345.0, "« Entry » doit primer sur « Zone clé »"
    assert lu.stop_loss == 77260.0
    assert lu.take_profits == [77430.0, 77515.0, 77600.0]


@pytest.mark.parametrize(
    "condition",
    [
        "Si cassure confirmée :",
        "Sur cassure du niveau :",
        "Après cassure :",
        "Si cassé :",
        "Dès cassure du niveau :",
        "On break above :",
        "If broken :",
        "If it breaks 77345 :",
        "Once it closes above 77345 :",
    ],
)
def test_les_formulations_subordonnees_posent_un_ordre_en_attente(
    condition: str,
) -> None:
    """Toutes portent un mot qui subordonne : si, sur, après, dès, on, if, once."""
    lu = deterministic_parser.parse(
        f"BTCUSD\n{condition}\nBUY\nEntry 77345\nSL 77260\nTP 77430"
    )

    assert lu.order_type is OrderType.BUY_STOP, f"« {condition} » non reconnue"


@pytest.mark.parametrize(
    "constat",
    [
        "Breakout confirmé",
        "Résistance cassée",
        "Breaks above 77345",
        "Close above 77345",
        "Cassure validée ce matin",
        "Higher Low détecté après cassure de la moyenne",
    ],
)
def test_un_constat_de_cassure_ne_pose_aucun_ordre_en_attente(constat: str) -> None:
    """Une cassure DEJA survenue ne conditionne rien : elle justifie l'entree.

    Cas reel du 12/09/2026 : un signal portait « Breakout confirmé » dans sa
    section d'analyse technique. Lu comme une condition, il devenait un ordre
    en attente a 77 205 alors que le marche cotait 77 290 -- un stop d'achat
    SOUS le marche, qui ne se serait jamais declenche.
    """
    lu = deterministic_parser.parse(
        f"BUY BTCUSD\nEntry 77205\nSL 76819\nTP 77591\n\nAnalyse :\n• {constat}"
    )

    assert lu.order_type is not OrderType.BUY_STOP, (
        f"« {constat} » decrit un fait accompli, il ne conditionne rien"
    )


def test_une_vente_sur_cassure_pose_un_sell_stop() -> None:
    lu = deterministic_parser.parse(
        "BTCUSD\nSi cassure sous le support :\nSELL\nEntry 77100\nSL 77200\nTP 77000"
    )

    assert lu.order_type is OrderType.SELL_STOP


def test_un_signal_ordinaire_reste_au_marche() -> None:
    """Le resserrage ne doit pas transformer tout signal en ordre en attente."""
    lu = deterministic_parser.parse(
        "BUY BTCUSD\nEntry 77345\nSL 77260\nTP1 77430"
    )

    assert lu.order_type is not OrderType.BUY_STOP


def test_un_type_d_ordre_explicite_prime_sur_la_condition() -> None:
    """L'auteur qui ecrit « BUY LIMIT » sait ce qu'il demande."""
    lu = deterministic_parser.parse(
        "BTCUSD\nSi cassure confirmée :\nBUY LIMIT 77100\nSL 77000\nTP 77300"
    )

    assert lu.order_type is OrderType.BUY_LIMIT


def test_une_zone_seule_reste_une_zone() -> None:
    """Sans ligne « Entry », la zone garde son role d'intervalle d'entree."""
    lu = deterministic_parser.parse(
        "BUY BTCUSD\nZone 77335 - 77345\nSL 77260\nTP 77430"
    )

    assert lu.entry_min == 77335.0
    assert lu.entry_max == 77345.0


def test_l_entree_explicite_gagne_meme_placee_apres_la_zone() -> None:
    """C'est l'ordre d'apparition qui faisait perdre la vraie entree."""
    lu = deterministic_parser.parse(
        "BUY BTCUSD\nZone clé : 77335 - 77345\nEntry 77345\nSL 77260\nTP 77430"
    )

    assert lu.entry_price == 77345.0


def test_le_mot_cassure_seul_ne_cree_pas_un_signal() -> None:
    """Un commentaire de marche n'est pas un ordre.

    Sans direction ni niveaux, « la cassure est confirmee » reste du bavardage.
    """
    lu = deterministic_parser.parse(
        "La cassure est confirmée sur BTCUSD, le marché accélère."
    )

    assert lu.is_signal is False
