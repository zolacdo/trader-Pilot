"""Une publicite ne doit pas remplir la liste des signaux.

Constate le 11/09/2026 sur l'ecran de l'utilisateur : deux cartes vides, sans
symbole, sans entree, sans stop, a 0 % de confiance. Le filtre cherchait ses
marqueurs par SOUS-CHAINE : « BE » se trouve dans BEGINNER et dans YOUTUBE,
« TP » dans HTTPS. Toute publicite contenant un lien etait donc enregistree.
"""

from __future__ import annotations

import pytest

from app.services.signals.pipeline import _looks_worth_recording

# Messages reellement recus le 11/09/2026, canaux 2 et 5.
PUBLICITE_VIDEO = """Featured Trading Video

PARAMOUR PSYCHO EA : HedgingMartingale 300 pip results

Watch here: https://www.youtube.com/watch?v=qIsbQAJD_Co"""

PUBLICITE_RECRUTEMENT = """IS IT HARD FOR A BEGINNER?
70% of our team consists of people with no trading experience. You can make
money with us from the very first day.

HOW MUCH CAN YOU EARN?
Up to +30-40% on your deposit in the first week, followed by stable 7-10%
every single week after that."""


@pytest.mark.parametrize(
    "message",
    [PUBLICITE_VIDEO, PUBLICITE_RECRUTEMENT],
    ids=["video_youtube", "recrutement"],
)
def test_une_publicite_n_est_pas_enregistree(message: str) -> None:
    assert not _looks_worth_recording(message)


@pytest.mark.parametrize(
    "mot_piege",
    ["BEGINNER", "YOUTUBE", "HTTPS", "BEFORE", "BEST", "CLOSELY", "SLOW", "LONGER"],
)
def test_les_mots_qui_contiennent_un_marqueur_ne_declenchent_rien(mot_piege: str) -> None:
    """Chacun de ces mots contient un marqueur sans porter aucune intention."""
    assert not _looks_worth_recording(f"Some ordinary sentence with {mot_piege} inside it")


@pytest.mark.parametrize(
    "message",
    [
        "BUY XAUUSD 4372",
        "SELL GOLD now",
        "TP1 4375 TP2 4378",
        "SL 4362",
        "Stop Loss: 4362",
        "Take Profit: 4375",
        "CLOSE the trade",
        "move to BE",
        "Entry 4372",
        "Target 4380",
        "going LONG on gold",
        "SHORT eurusd",
    ],
)
def test_un_message_qui_porte_une_intention_est_enregistre(message: str) -> None:
    """Le resserrage ne doit pas faire perdre de messages utiles."""
    assert _looks_worth_recording(message)


def test_un_message_vide_n_est_pas_enregistre() -> None:
    assert not _looks_worth_recording("")
    assert not _looks_worth_recording("   ")
