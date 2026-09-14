"""Une option binaire n'est pas un ordre : elle ne doit jamais entrer dans la chaine.

Message reellement recu le 13/09/2026 sur le canal « Forex Signals Trading »,
un dimanche, marche forex ferme :

    SIGNAL
    EUR/GBP  OTC
    Timeframe: M5
    Expiration: 5 minutes
    Entry: 09:50
    Direction: BUY
    Martingale: 09:55 / 10:00 / 10:05

Il n'y a la ni prix d'entree, ni stop, ni objectif -- une option binaire n'en a
pas. « Entry » designe une HEURE. Le systeme passe des ordres CFD sur
MetaTrader : il n'y a rien a executer.

Ces messages etaient bien refuses, mais **par accident** : sur le plancher de
confiance (0.50 contre 0.75 exige). Le jour ou l'un d'eux serait lu avec plus
d'assurance -- un canal plus bavard, un modele d'IA plus genereux -- il
atteindrait l'execution avec une entree nulle, et le RiskManager se rabattrait
sur le prix du marche pour ouvrir une position SANS STOP.

Ces tests ferment cette porte, et verifient surtout qu'elle ne se referme pas
sur les signaux legitimes.
"""

from __future__ import annotations

import pytest

from app.services.signals import deterministic_parser

EURGBP = """🔔 SIGNAL

💱 EUR/GBP 🔶 OTC
Timeframe: M5
⏱ Expiration: 5 minutes
📥 Entry: 09:50
📈 Direction: BUY

♻ Martingale:
1️⃣ 09:55
2️⃣ 10:00
3️⃣ 10:05"""

EURUSD = """🔔 SIGNAL

💱 EUR/USD 🔶 OTC
Timeframe: M5
⏱ Expiration: 5 minutes
📥 Entry: 10:05
📈 Direction: SELL

♻ Martingale:
1️⃣ 10:10
2️⃣ 10:15
3️⃣ 10:20"""


class TestMessagesReels:
    @pytest.mark.parametrize("message", [EURGBP, EURUSD], ids=["EUR/GBP", "EUR/USD"])
    def test_les_deux_messages_recus_sont_ecartes(self, message: str) -> None:
        lu = deterministic_parser.parse(message)

        assert lu.is_signal is False
        assert "option_binaire_non_executable" in lu.warnings

    @pytest.mark.parametrize("message", [EURGBP, EURUSD], ids=["EUR/GBP", "EUR/USD"])
    def test_aucun_niveau_n_est_invente(self, message: str) -> None:
        """Le danger etait la : une entree nulle devient le prix du marche."""
        lu = deterministic_parser.parse(message)

        assert lu.entry_price is None
        assert lu.stop_loss is None
        assert lu.take_profits == []

    def test_l_heure_d_entree_ne_devient_jamais_un_prix(self) -> None:
        """« Entry: 09:50 » vaut neuf heures cinquante, pas 9.50 sur EUR/GBP."""
        lu = deterministic_parser.parse(EURGBP)

        assert lu.entry_price != 9.50
        assert lu.entry_price is None


class TestMarqueurs:
    """Un seul marqueur suffit : ils ne se rencontrent pas ailleurs."""

    def test_la_martingale_suffit(self) -> None:
        lu = deterministic_parser.parse(
            "BUY EURUSD\nEntry: 1.1650\nSL: 1.1600\nTP: 1.1700\nMartingale: 3 paliers"
        )

        assert lu.is_signal is False, "une consigne de martingale doit tout arreter"

    def test_le_marqueur_otc_suffit(self) -> None:
        lu = deterministic_parser.parse("SIGNAL\nEUR/USD OTC\nDirection: BUY")

        assert lu.is_signal is False

    def test_une_expiration_en_minutes_suffit(self) -> None:
        lu = deterministic_parser.parse(
            "SIGNAL\nGBP/JPY\nExpiration: 3 minutes\nDirection: SELL"
        )

        assert lu.is_signal is False

    def test_le_detecteur_ignore_la_casse_et_les_accents(self) -> None:
        lu = deterministic_parser.parse("signal\neur/usd\nexpiration : 5 min\ndirection: buy")

        assert lu.is_signal is False


class TestAucunFauxPositif:
    """Se tromper dans ce sens couterait des signaux legitimes."""

    def test_un_signal_cfd_complet_passe(self) -> None:
        lu = deterministic_parser.parse(
            "BUY XAUUSD\nEntry: 2400.00\nSL: 2390.00\nTP1: 2420.00\nTP2: 2440.00"
        )

        assert lu.is_signal is True
        assert lu.entry_price == 2400.00
        assert lu.stop_loss == 2390.00

    def test_un_signal_sur_une_paire_avec_barre_passe(self) -> None:
        """La barre d'EUR/USD n'est pas un marqueur d'option binaire."""
        lu = deterministic_parser.parse(
            "SELL EUR/USD\nEntry: 1.1650\nSL: 1.1700\nTP: 1.1550"
        )

        assert lu.is_signal is True
        assert lu.entry_price == 1.1650

    def test_le_mot_protocole_contenant_otc_ne_declenche_rien(self) -> None:
        """« OTC » doit etre un mot isole, pas une suite de lettres."""
        lu = deterministic_parser.parse(
            "BUY BTCUSD\nEntry: 77000\nSL: 76500\nTP: 77500\nNote: BOTCHED setup evite"
        )

        assert lu.is_signal is True, "OTC au milieu d'un mot ne doit rien declencher"

    def test_une_heure_d_expiration_sans_duree_ne_declenche_rien(self) -> None:
        """Un ordre en attente peut legitimement porter une echeance."""
        lu = deterministic_parser.parse(
            "BUY LIMIT XAUUSD\nEntry: 2400.00\nSL: 2390.00\nTP: 2420.00\n"
            "Expiration: fin de journee"
        )

        assert lu.is_signal is True

    def test_un_message_francais_reste_lu(self) -> None:
        lu = deterministic_parser.parse(
            "ACHAT ETHUSD\nEntree : 2532.24\nStop loss : 2527.19\nTP1 : 2536.19"
        )

        assert lu.is_signal is True
        assert lu.entry_price == 2532.24
