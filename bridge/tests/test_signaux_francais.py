"""Un signal redige en francais doit etre lu aussi bien qu'en anglais.

Message reellement recu le 12/09/2026. Son stop et ses trois objectifs etaient
parfaitement lus -- « Stop loss » et « TP » s'ecrivent pareil dans les deux
langues -- mais son PRIX D'ENTREE ressortait a ``None`` : l'etiquette
« Entree » ne figurait nulle part dans les expressions du parser, entierement
anglaises.

Un signal sans entree n'est pas inoffensif : le RiskManager se rabat alors sur
le prix du marche, ce qui peut differer sensiblement du prix demande, et le
rapport rendement/risque calcule devient faux.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction, OrderType
from app.services.signals import deterministic_parser

ETHUSD = """🚨 ETHUSD — SIGNAL BUY

🟢 BUY ETHUSD
Entree (MARKET) : 2 532.24
Stop loss : 2 527.19

TP1 : 2 536.19  (1:0.78)
TP2 : 2 542.83  (1:2.1)
TP3 : 2 547.39  (1:3.0)

Confiance : 72/100

Unites de temps
D1   🟢 bullish
H4   🟢 bullish
H1   🟢 bullish

Pourquoi
• Entree au marche, au prix demande courant.
• Stop sous le dernier creux protecteur 2528.23.
• TP1 sur la zone technique 2536.19 (0.78R).

Risques
• Volume : Activite faible : 58 % du tick volume habituel.

Invalidation
Cloture M15 sous 2527.19."""


def test_le_signal_francais_est_lu_en_entier() -> None:
    lu = deterministic_parser.parse(ETHUSD)

    assert lu.is_signal is True
    assert lu.symbol == "ETHUSD"
    assert lu.direction is Direction.BUY
    assert lu.order_type is OrderType.MARKET
    assert lu.entry_price == 2532.24, "« Entree » n'etait pas reconnu comme etiquette"
    assert lu.stop_loss == 2527.19
    assert lu.take_profits == [2536.19, 2542.83, 2547.39]


def test_les_milliers_separes_par_une_espace_sont_lus() -> None:
    """« 2 532.24 » vaut deux mille cinq cent trente-deux, pas deux."""
    lu = deterministic_parser.parse(ETHUSD)

    assert lu.entry_price == 2532.24
    assert lu.entry_price > 2000, "l'espace des milliers a coupe le nombre"


def test_les_ratios_entre_parentheses_ne_deviennent_pas_des_objectifs() -> None:
    """« (1:0.78) » decrit un rapport, pas un prix.

    Sans ce filtre, 0.78 et 2.1 se seraient glisses dans les objectifs.
    """
    lu = deterministic_parser.parse(ETHUSD)

    for valeur in lu.take_profits:
        assert valeur > 2000, f"{valeur} n'est pas un prix d'ETHUSD"


@pytest.mark.parametrize(
    "etiquette",
    ["Entree", "Entrée", "ENTREE", "ENTRÉE", "Entrees", "Prix d'entree"],
)
def test_les_graphies_francaises_de_l_entree_sont_acceptees(etiquette: str) -> None:
    """Le normaliseur conserve les accents : les deux formes doivent figurer."""
    lu = deterministic_parser.parse(
        f"BUY ETHUSD\n{etiquette} : 2532.24\nStop loss : 2527.19\nTP : 2536.19"
    )

    assert lu.entry_price == 2532.24, f"« {etiquette} » non reconnue"


def test_un_signal_anglais_reste_lu() -> None:
    """L'ajout du francais ne doit rien retirer a l'anglais."""
    lu = deterministic_parser.parse(
        "BUY ETHUSD\nEntry: 2532.24\nStop loss: 2527.19\nTP1: 2536.19"
    )

    assert lu.entry_price == 2532.24
    assert lu.stop_loss == 2527.19
