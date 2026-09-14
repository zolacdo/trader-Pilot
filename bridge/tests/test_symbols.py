"""Reconnaissance des instruments : alias, paires, suffixes broker.

Le piege principal est le faux positif : un mot anglais courant ne doit jamais
etre pris pour un instrument, sous peine d'ouvrir une position sur un symbole
que le canal n'a jamais mentionne.
"""

from __future__ import annotations

import pytest

from app.services.signals.symbols import (
    ALIASES,
    all_aliases_for,
    canonical_symbol,
    clean_token,
    extract_symbol,
    is_currency_pair,
    strip_broker_suffix,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GOLD", "XAUUSD"),
        ("gold", "XAUUSD"),
        ("XAU", "XAUUSD"),
        ("XAUUSD", "XAUUSD"),
        ("XAU/USD", "XAUUSD"),
        ("XAU-USD", "XAUUSD"),
        ("SILVER", "XAGUSD"),
        ("GU", "GBPUSD"),
        ("EU", "EURUSD"),
        ("UJ", "USDJPY"),
        ("GJ", "GBPJPY"),
        ("CABLE", "GBPUSD"),
        ("FIBER", "EURUSD"),
        ("NASDAQ", "NAS100"),
        ("NASDAQ100", "NAS100"),
        ("USTEC", "NAS100"),
        ("DOW", "US30"),
        ("DJI", "US30"),
        ("DAX", "GER40"),
        ("GER30", "GER40"),
        ("SP500", "SPX500"),
        ("FTSE", "UK100"),
        ("NIKKEI", "JP225"),
        ("BITCOIN", "BTCUSD"),
        ("BTC", "BTCUSD"),
        ("BTCUSDT", "BTCUSD"),
        ("WTI", "XTIUSD"),
        ("BRENT", "XBRUSD"),
        # paires ecrites directement
        ("EURUSD", "EURUSD"),
        ("usdchf", "USDCHF"),
        ("NZDCAD", "NZDCAD"),
    ],
)
def test_canonical_symbol_resout_les_alias(raw: str, expected: str) -> None:
    assert canonical_symbol(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        # mots anglais frequents dans les canaux : jamais des instruments
        "BUY",
        "SELL",
        "LONG",
        "SHORT",
        "STOP",
        "LIMIT",
        "ENTRY",
        "TARGET",
        "CLOSE",
        "PROFIT",
        "NOW",
        "HIT",
        "THE",
        "AND",
        "FAMILY",
        "MORNING",
        "RUNNING",
        "PIPS",
        "",
        None,
    ],
)
def test_canonical_symbol_refuse_les_mots_courants(raw: str | None) -> None:
    assert canonical_symbol(raw) is None


def test_is_currency_pair() -> None:
    assert is_currency_pair("EURUSD") is True
    assert is_currency_pair("eur/usd") is True
    assert is_currency_pair("XAUUSD") is True
    assert is_currency_pair("US30") is False
    assert is_currency_pair("EURXXX") is False
    assert is_currency_pair("EUR") is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("XAUUSDm", "XAUUSD"),
        ("XAUUSDM", "XAUUSD"),
        ("EURUSDz", "EURUSD"),
        ("EURUSDc", "EURUSD"),
        ("GBPUSDe", "GBPUSD"),
        ("XAUUSDmicro", "XAUUSD"),
        ("EURUSDpro", "EURUSD"),
    ],
)
def test_canonical_symbol_tolere_les_suffixes_broker(raw: str, expected: str) -> None:
    assert canonical_symbol(raw) == expected


def test_strip_broker_suffix() -> None:
    assert strip_broker_suffix("XAUUSDm") == "XAUUSD"
    assert strip_broker_suffix("EURUSDz") == "EURUSD"
    assert strip_broker_suffix("EURUSD") == "EURUSD"


def test_clean_token_retire_la_ponctuation() -> None:
    assert clean_token("xau/usd") == "XAUUSD"
    assert clean_token("XAUUSD.r") == "XAUUSDR"


# ---------------------------------------------------------------------------
# Recherche dans du texte libre
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("GOLD BUY NOW", "XAUUSD"),
        ("XAU/USD LONG", "XAUUSD"),
        ("XAU USD LONG", "XAUUSD"),
        ("BUY XAUUSD.r AT MARKET", "XAUUSD"),
        ("nous surveillons EURUSD de pres", "EURUSD"),
        ("we are watching gold closely", "XAUUSD"),
        ("US30 SELL 44250", "US30"),
        ("SELL NAS100 NOW", "NAS100"),
        ("BUY XAUUSDm 3320", "XAUUSD"),
    ],
)
def test_extract_symbol_trouve_l_instrument(text: str, expected: str) -> None:
    raw, canonical = extract_symbol(text)
    assert canonical == expected
    assert raw is not None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Please close the trade now",
        "GOOD MORNING FAMILY",
        "TP1 HIT MOVE SL BE",
        "Congratulations everyone",
    ],
)
def test_extract_symbol_ne_devine_rien(text: str) -> None:
    assert extract_symbol(text) == (None, None)


def test_extract_symbol_accepte_des_alias_de_canal() -> None:
    aliases = {"YELLOW METAL": "XAUUSD", "DAXY": "GER40"}
    assert extract_symbol("BUY DAXY NOW", aliases)[1] == "GER40"
    # Sans l'alias du canal, le meme mot n'est pas un instrument.
    assert extract_symbol("BUY DAXY NOW")[1] is None


def test_all_aliases_for_contient_le_symbole_canonique() -> None:
    aliases = all_aliases_for("XAUUSD")
    assert "XAUUSD" in aliases
    assert "GOLD" in aliases
    assert aliases == sorted(aliases)


def test_la_table_d_alias_ne_contient_aucun_mot_de_commande() -> None:
    """Aucun mot-cle de trading ne doit figurer comme alias d'instrument."""
    interdits = {"BUY", "SELL", "LONG", "SHORT", "TP", "SL", "ENTRY", "CLOSE", "STOP", "LIMIT"}
    assert interdits.isdisjoint(ALIASES)
