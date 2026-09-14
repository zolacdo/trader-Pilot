"""Normalisation d'un message Telegram avant analyse.

Un canal ecrit ses signaux avec des emojis, des majuscules aleatoires, des
separateurs exotiques et des chiffres formates a l'europeenne. La normalisation
doit rendre tout cela comparable SANS jamais alterer la valeur d'un nombre.
"""

from __future__ import annotations

import pytest

from app.services.signals.normalizer import (
    collapse_for_matching,
    content_hash,
    extract_numbers,
    looks_like_noise,
    normalize,
    normalize_numbers,
    normalize_upper,
    strip_emojis,
    structure_fingerprint,
)
from tests.fixtures.messages import NOISE_MESSAGES

NBSP = "\u00a0"
NARROW_NBSP = "\u202f"
ZERO_WIDTH = "\u200b"


def test_strip_emojis_retire_emojis_et_decorations() -> None:
    assert strip_emojis("\U0001f525 GOLD BUY \U0001f3af").strip() == "GOLD BUY"
    assert strip_emojis("★ XAUUSD • SELL").replace(" ", "") == "XAUUSDSELL"


def test_normalize_supprime_emojis_et_espaces_superflus() -> None:
    assert normalize("\U0001f525 GOLD BUY \U0001f525") == "GOLD BUY"
    assert normalize("  GOLD   BUY  \n   SL 3310  ") == "GOLD BUY\nSL 3310"
    assert normalize("GOLD BUY NOW\n\n\n\nSL 3310") == "GOLD BUY NOW\nSL 3310"


def test_normalize_vide_reste_vide() -> None:
    assert normalize("") == ""
    assert normalize("   \n  \n ") == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SL: 3310", "SL 3310"),
        ("SL @ 3310", "SL 3310"),
        ("SL -> 3310", "SL 3310"),
        ("SL => 3310", "SL 3310"),
        ("SL = 3310", "SL 3310"),
    ],
)
def test_normalize_uniformise_les_separateurs_d_etiquette(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # virgule decimale europeenne
        ("3320,50", "3320.50"),
        # separateur de milliers anglo-saxon
        ("3,320.50", "3320.50"),
        ("44,250.0", "44250.0"),
        # espace de milliers, insecable ou non
        ("3 320.50", "3320.50"),
        (f"3{NBSP}320.50", "3320.50"),
        (f"3{NARROW_NBSP}320.50", "3320.50"),
        # une liste de prix ne doit surtout pas etre recollee
        ("3330, 3320, 3300", "3330, 3320, 3300"),
        # le numero d'objectif ne doit pas etre colle au prix
        ("TP1 194.800", "TP1 194.800"),
    ],
)
def test_normalize_numbers_preserve_les_valeurs(raw: str, expected: str) -> None:
    assert normalize_numbers(raw) == expected


def test_normalize_convertit_les_tirets_longs() -> None:
    assert normalize("3320\u20143315") == "3320-3315"
    assert normalize("3320\u20133315") == "3320-3315"
    assert normalize("3320\u22123315") == "3320-3315"


def test_normalize_supprime_les_caracteres_de_largeur_nulle() -> None:
    assert normalize(f"XAU{ZERO_WIDTH}USD BUY") == "XAUUSD BUY"


def test_normalize_upper_met_en_majuscules() -> None:
    assert normalize_upper("gold buy now") == "GOLD BUY NOW"


def test_extract_numbers_lit_les_prix_dans_l_ordre() -> None:
    assert extract_numbers("ENTRY 3 320,50 SL 3310 TP 3340") == [3320.5, 3310.0, 3340.0]
    assert extract_numbers("aucun prix ici") == []


def test_collapse_for_matching_ne_garde_que_les_alphanumeriques() -> None:
    assert collapse_for_matching("Gold Buy!! 3320") == "GOLDBUY3320"


# ---------------------------------------------------------------------------
# Empreinte de contenu
# ---------------------------------------------------------------------------

def test_content_hash_insensible_a_la_mise_en_forme() -> None:
    reference = content_hash("GOLD BUY NOW\nSL 3310\nTP 3330")
    assert content_hash("  gold buy now  \n\n sl: 3310 \n tp: 3330 ") == reference
    assert content_hash("\U0001f525 GOLD BUY NOW \U0001f525\nSL 3310\nTP 3330") == reference
    assert content_hash("GOLD BUY NOW | SL 3310 | TP 3330") == reference


def test_content_hash_change_des_qu_une_valeur_change() -> None:
    reference = content_hash("GOLD BUY NOW\nSL 3310\nTP 3330")
    assert content_hash("GOLD SELL NOW\nSL 3310\nTP 3330") != reference
    assert content_hash("GOLD BUY NOW\nSL 3311\nTP 3330") != reference


def test_content_hash_est_stable_et_court() -> None:
    first = content_hash("XAUUSD BUY\nENTRY 3320")
    assert first == content_hash("XAUUSD BUY\nENTRY 3320")
    assert len(first) == 32


# ---------------------------------------------------------------------------
# Signature de structure
# ---------------------------------------------------------------------------

def test_structure_fingerprint_identique_pour_un_meme_gabarit() -> None:
    first = structure_fingerprint("XAUUSD BUY\nENTRY 3320\nSL 3310\nTP1 3330\nTP2 3340")
    second = structure_fingerprint("GOLD BUY\nENTRY 3350\nSL 3340\nTP1 3360\nTP2 3370")
    assert first == second == "BUY|ENTRY|SL|TP1|TP2"


def test_structure_fingerprint_differe_selon_le_gabarit() -> None:
    first = structure_fingerprint("XAUUSD BUY\nENTRY 3320\nSL 3310\nTP1 3330")
    second = structure_fingerprint("Sell gold now @ 3341\nstop 3350\ntargets 3330")
    assert first != second


def test_structure_fingerprint_ignore_le_texte_libre() -> None:
    assert structure_fingerprint("Good morning family") == ""


# ---------------------------------------------------------------------------
# Detection du bavardage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "GOOD MORNING FAMILY",
        "Welcome to the channel",
        "Congratulations everyone",
        "Join our VIP channel now",
        "",
        "   ",
        "ok",
    ],
)
def test_looks_like_noise_detecte_la_convivialite(text: str) -> None:
    assert looks_like_noise(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "GOLD BUY NOW\nSL 3310\nTP 3330",
        "XAUUSD SELL 3350",
        # Un message de convivialite QUI PORTE des chiffres n'est pas ecarte
        # d'office : c'est au parser de trancher.
        "GOOD MORNING FAMILY, GOLD BUY 3320",
    ],
)
def test_looks_like_noise_ne_jette_pas_un_signal(text: str) -> None:
    assert looks_like_noise(text) is False


def test_les_messages_de_bruit_du_dataset_ne_cassent_pas_la_normalisation() -> None:
    for label, text in NOISE_MESSAGES:
        assert isinstance(normalize(text), str), label
        assert isinstance(content_hash(text), str), label
