"""Cinq facons reelles d'ecrire un signal, toutes recues le 12/09/2026.

Les canaux n'ont aucune convention commune. Ces messages viennent tous de
vraies sources et servent de banc d'essai : si le parser regresse sur l'un
d'eux, un format entier redevient illisible.

Le piege documente ici vaut d'etre retenu. En elargissant les separateurs de
zone pour accepter « 4640_4635 » et « 4307//4304 », j'y avais inclus le POINT.
Consequence immediate : « Entry: 154.387 » etait lu comme une zone allant de
154 a 387, et « 1.38104 » comme une zone de 1 a 38104. Deux formats repares,
deux autres casses.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction, OrderType
from app.services.signals import deterministic_parser

# --- Format a etiquettes et emojis -----------------------------------------

USDJPY = """📊 USDJPY – BUY
Entry: 154.387

🎯Take Profit Targets
TP1: 154.657
TP2: 154.926
TP3: 155.465

⏺️Stop Loss: 153.848"""

USDCAD = """📊 USDCAD – SELL
Entry: 1.38104

🎯Take Profit Targets
TP1: 1.37800
TP2: 1.37600
TP3: 1.37322

⏺️Stop Loss: 1.38300"""

# --- Formats compacts a zone -----------------------------------------------

XAU_SOULIGNE = """XAUUSD BUY 4640_4635

TP 4645
TP 4650
TP 4655
TP 4660
TP 4665
TP 4670

SL 4627"""

XAU_DOUBLE_BARRE = """XAUUSD BUY  4307//4304

✅TP 4310
✅TP 4313
✅TP 4316
✅TP 4320
✅TP 4324
✅TP 4328
✅TP 4334

      SL 4297"""


def test_les_emojis_n_empechent_pas_la_lecture() -> None:
    lu = deterministic_parser.parse(USDJPY)

    assert lu.is_signal is True
    assert lu.symbol == "USDJPY"
    assert lu.direction is Direction.BUY
    assert lu.entry_price == 154.387
    assert lu.stop_loss == 153.848
    assert lu.take_profits == [154.657, 154.926, 155.465]


def test_un_prix_decimal_n_est_jamais_lu_comme_une_zone() -> None:
    """Le piege exact : « 154.387 » n'est pas une zone de 154 a 387.

    En incluant le point parmi les separateurs de zone, ce prix devenait un
    intervalle absurde et le stop se retrouvait a l'interieur.
    """
    lu = deterministic_parser.parse(USDJPY)

    assert lu.entry_min is None, "un prix decimal a ete pris pour une zone"
    assert lu.entry_price == 154.387


def test_un_prix_a_cinq_decimales_reste_entier() -> None:
    lu = deterministic_parser.parse(USDCAD)

    assert lu.direction is Direction.SELL
    assert lu.entry_price == 1.38104
    assert lu.entry_min is None
    assert lu.stop_loss == 1.38300


def test_une_zone_ecrite_avec_un_souligne_est_lue() -> None:
    """« 4640_4635 » : la seconde borne etait perdue."""
    lu = deterministic_parser.parse(XAU_SOULIGNE)

    assert lu.entry_min == 4635.0
    assert lu.entry_max == 4640.0
    assert lu.stop_loss == 4627.0
    assert len(lu.take_profits) == 6


def test_une_zone_ecrite_avec_une_double_barre_est_lue() -> None:
    """« 4307//4304 » : idem, et le double separateur n'etait pas reconnu."""
    lu = deterministic_parser.parse(XAU_DOUBLE_BARRE)

    assert lu.entry_min == 4304.0
    assert lu.entry_max == 4307.0
    assert lu.stop_loss == 4297.0
    assert len(lu.take_profits) == 7


@pytest.mark.parametrize(
    ("ecriture", "attendu"),
    [
        ("4640-4635", (4635.0, 4640.0)),
        ("4640_4635", (4635.0, 4640.0)),
        ("4640//4635", (4635.0, 4640.0)),
        ("4640/4635", (4635.0, 4640.0)),
        ("4640 ~ 4635", (4635.0, 4640.0)),
        ("4640 - 4635", (4635.0, 4640.0)),
    ],
)
def test_les_ecritures_de_zone_donnent_le_meme_resultat(
    ecriture: str, attendu: tuple[float, float]
) -> None:
    lu = deterministic_parser.parse(f"XAUUSD BUY {ecriture}\nTP 4650\nSL 4627")

    assert (lu.entry_min, lu.entry_max) == attendu


def test_des_objectifs_repetes_sans_numero_sont_tous_gardes() -> None:
    """« TP 4645 » repete six fois : aucun ne doit ecraser les autres."""
    lu = deterministic_parser.parse(XAU_SOULIGNE)

    assert lu.take_profits == [4645.0, 4650.0, 4655.0, 4660.0, 4665.0, 4670.0]


def test_les_quatre_formats_restent_des_signaux_exploitables() -> None:
    """Garde-fou global : chacun doit porter de quoi passer un ordre."""
    for message in (USDJPY, USDCAD, XAU_SOULIGNE, XAU_DOUBLE_BARRE):
        lu = deterministic_parser.parse(message)
        assert lu.is_signal is True
        assert lu.symbol is not None
        assert lu.direction is not None
        assert lu.stop_loss is not None
        assert lu.take_profits
        assert lu.entry_price is not None or lu.entry_min is not None
        # Aucun de ces messages n'annonce de cassure : ils partent au marche.
        assert lu.order_type is not OrderType.BUY_STOP
