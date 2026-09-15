"""Un ratio rendement/risque n'est pas un prix.

Le signal 128 du 14/09/2026, annote « TP1 : 1.15396  (1:1.0) », ressortait du
parser avec ``take_profits = [1.0, 2.0, 3.0, 1.15396, 1.15237, 1.15079]`` :
les trois ratios avaient ete lus comme des objectifs, et sans le moindre
avertissement.

``_plausible`` existe pour ecarter « TARGET 1 » lu comme le prix 1,0, mais il
juge par ordre de grandeur (0,3 a 3 fois l'entree). Sur une paire qui cote
1,155, les nombres 1, 2 et 3 sont precisement du bon ordre de grandeur : le
filtre ne peut rien voir.

Ce que ca coutait. La position #3223022249 est partie avec un take profit a
1,0 -- 1355 pips sous l'entree, donc hors d'atteinte -- et 40 % du volume lui
etait affecte par la sortie en paliers. Le rendement attendu calcule par
``quality.py`` etait gonfle par ces faux objectifs, donc le signal passait pour
excellent. Depuis le 14/09 11:02 le validateur bloque le message entier pour
``TP_WRONG_SIDE`` : plus de mauvais trade, mais le signal est perdu au lieu
d'etre lu correctement.
"""

from __future__ import annotations

from app.models.enums import Direction
from app.services.signals import deterministic_parser as parser
from app.services.signals import validator

MESSAGE = """EURUSD - SIGNAL SELL

SELL EURUSD
Entree (BREAKOUT) : 1.15554
Stop loss : 1.15712

TP1 : 1.15396  (1:1.0)
TP2 : 1.15237  (1:2.0)
TP3 : 1.15079  (1:3.0)

Confiance : 73/100
"""


class TestLesRatiosNeSontPasDesObjectifs:
    def test_seuls_les_vrais_take_profits_sont_retenus(self) -> None:
        signal = parser.parse(MESSAGE)
        assert signal.take_profits == [1.15396, 1.15237, 1.15079]

    def test_le_signal_redevient_structurellement_valide(self) -> None:
        """Sans cela le validateur rejette tout le message : signal perdu."""
        signal = parser.parse(MESSAGE)
        resultat = validator.validate(signal)
        assert resultat.ok, [issue.code for issue in resultat.issues]

    def test_lentree_et_le_stop_restent_intacts(self) -> None:
        signal = parser.parse(MESSAGE)
        assert signal.direction is Direction.SELL
        assert signal.entry_price == 1.15554
        assert signal.stop_loss == 1.15712

    def test_un_ratio_colle_sans_espace_est_aussi_ecarte(self) -> None:
        signal = parser.parse(
            "BUY XAUUSD\nEntree : 4267\nSL : 4255\nTP1 : 4270 (1:1)\nTP2 : 4276 (1:2)"
        )
        assert signal.take_profits == [4270.0, 4276.0]

    def test_la_notation_rr_hors_parentheses_est_ecartee(self) -> None:
        signal = parser.parse(
            "SELL XAUUSD\nEntree : 4269\nSL : 4279\nR:R 1:3\nTP1 : 4259\nTP2 : 4249"
        )
        assert signal.take_profits == [4259.0, 4249.0]


class TestAucuneRegressionSurLesPrix:
    def test_un_prix_apres_deux_points_reste_un_prix(self) -> None:
        """Le piege du correctif : « TP1 : 1.15396 » contient aussi un deux-points."""
        signal = parser.parse(MESSAGE)
        assert 1.15396 in signal.take_profits

    def test_un_horaire_reste_ecarte(self) -> None:
        signal = parser.parse("12:05 - EURUSD - SELL\nEntree 1.15554\nSL 1.15712\nTP 1.15396")
        assert signal.entry_price == 1.15554
        assert 12.0 not in (signal.take_profits or [])

    def test_un_signal_sans_annotation_est_inchange(self) -> None:
        signal = parser.parse("BUY GOLD\nENTRY 3320\nSL 3310\nTP1 3330\nTP2 3340")
        assert signal.take_profits == [3330.0, 3340.0]
