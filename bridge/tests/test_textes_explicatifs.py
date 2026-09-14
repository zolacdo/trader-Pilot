"""Un article ou un cours n'est pas un ordre a executer.

Constate en production le 11/09/2026 en lisant l'historique de vrais canaux :
un article sur Bitcoin est ressorti en « BTCUSD SELL », et un message
pedagogique intitule « HOW I LAYER MY ENTRIES » en « XAUUSD BUY a 60,0 ».
Seule l'exigence de stop loss les arretait -- par chance, pas par regle.
"""

from __future__ import annotations

from app.models.enums import Direction
from app.services.signals import deterministic_parser

# Extrait reel de @signalsbitcoinandethereum.
ARTICLE_BITCOIN = """According to data from CryptoQuant, the recent rise in Bitcoin has been
driven by the closing of short positions rather than by fresh spot demand. Analysts
note that whenever open interest falls while price climbs, the move tends to be a
short squeeze. Several desks now expect bitcoin to sell off once the squeeze is
exhausted, and they point to the same pattern observed in previous cycles. Traders
should remain cautious, because funding rates have turned negative again and
liquidity on the major venues remains thin for this time of the year."""

# Extrait reel de @BTCUSD_TRADINGSIGNALSFREE.
COURS_SUR_LES_ENTREES = """HOW I LAYER MY ENTRIES

When I say GOLD BUY NOW, it means the price has reached the zone I had marked in
advance on my chart. I never put everything on a single entry. I take a first
position of about 30 percent of what I intend to risk, then I wait. If price moves
against me by a few dollars I add a second layer, and only then do I consider a
third one. This is how I keep my average price under control when the market is
choppy and how I avoid being stopped out on noise before the real move begins."""


def test_un_article_de_presse_n_est_pas_un_ordre() -> None:
    lu = deterministic_parser.parse(ARTICLE_BITCOIN)

    assert not lu.is_signal, f"article lu comme {lu.symbol} {lu.direction}"
    assert "texte_explicatif_sans_ordre" in lu.warnings


def test_un_message_pedagogique_n_est_pas_un_ordre() -> None:
    lu = deterministic_parser.parse(COURS_SUR_LES_ENTREES)

    assert not lu.is_signal, f"cours lu comme {lu.symbol} {lu.direction} a {lu.entry_price}"
    assert "texte_explicatif_sans_ordre" in lu.warnings


def test_un_ordre_au_marche_tres_court_reste_lu() -> None:
    """La regle ne doit pas avaler les signaux minimalistes.

    « BUY GOLD NOW » n'a ni stop ni objectif, mais il tient en trois mots :
    c'est bien une intention d'execution.
    """
    lu = deterministic_parser.parse("BUY GOLD NOW")

    assert lu.is_signal
    assert lu.symbol == "XAUUSD"
    assert lu.direction is Direction.BUY


def test_un_signal_commente_longuement_reste_lu() -> None:
    """Un signal accompagne d'une analyse garde sa structure : il passe."""
    texte = (
        "XAUUSD BUY 4388\nSL 4380\nTP1 4393\nTP2 4398\n\n"
        + "Gold is reacting on the daily demand zone that has held three times since "
        "the beginning of the month, and the dollar index is losing momentum right "
        "at its own resistance. Volume on the last four hourly candles confirms "
        "buyers stepping in, so I am comfortable taking this long with a tight stop "
        "under the zone and scaling out at the levels above."
    )
    lu = deterministic_parser.parse(texte)

    assert lu.is_signal
    assert lu.symbol == "XAUUSD"
    assert lu.direction is Direction.BUY
    assert lu.stop_loss == 4380.0
    assert lu.take_profits == [4393.0, 4398.0]


def test_un_signal_btc_ordinaire_reste_lu() -> None:
    """Controle de non-regression sur la crypto, que l'utilisateur veut trader."""
    lu = deterministic_parser.parse("BUY BTCUSD\nEntry 77500\nSL 77000\nTP1 78000\nTP2 78500")

    assert lu.is_signal
    assert lu.symbol == "BTCUSD"
    assert lu.direction is Direction.BUY
    assert lu.entry_price == 77500.0
    assert lu.stop_loss == 77000.0
