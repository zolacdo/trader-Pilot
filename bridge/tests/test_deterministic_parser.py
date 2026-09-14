"""Parser deterministe : il lit ce qui est ecrit, et rien d'autre.

Regle fondamentale verifiee ici : une information absente du message reste
``None``. Le parser n'invente jamais un prix, une direction ni un instrument.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction, OrderType, ParserSource
from app.services.signals import validator
from app.services.signals.deterministic_parser import parse, parse_symbol_only
from tests.fixtures.messages import (
    AMBIGUOUS_MESSAGES,
    CLEAN_SIGNALS,
    NOISE_MESSAGES,
    AmbiguousCase,
    SignalCase,
)


def _ids(cases: tuple) -> list[str]:
    return [case.label if hasattr(case, "label") else case[0] for case in cases]


# ---------------------------------------------------------------------------
# Signaux propres : chaque champ attendu est verifie
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", CLEAN_SIGNALS, ids=_ids(CLEAN_SIGNALS))
def test_signaux_propres_sont_interpretes_champ_par_champ(case: SignalCase) -> None:
    signal = parse(case.text)

    assert signal.is_signal is True, case.label
    assert signal.source is ParserSource.DETERMINISTIC
    assert signal.symbol == case.symbol
    assert signal.direction is case.direction
    assert signal.order_type is case.order_type
    assert signal.stop_loss == case.stop_loss
    assert tuple(signal.take_profits) == case.take_profits
    assert signal.entry_price == case.entry_price
    assert signal.entry_min == case.entry_min
    assert signal.entry_max == case.entry_max
    if case.confidence is not None:
        assert signal.confidence == pytest.approx(case.confidence)


@pytest.mark.parametrize("case", CLEAN_SIGNALS, ids=_ids(CLEAN_SIGNALS))
def test_signaux_propres_passent_le_validateur(case: SignalCase) -> None:
    signal = validator.sanitize(parse(case.text))
    result = validator.validate(signal)
    assert result.ok is True, f"{case.label} : {[issue.code for issue in result.issues]}"


@pytest.mark.parametrize("case", CLEAN_SIGNALS, ids=_ids(CLEAN_SIGNALS))
def test_un_signal_a_toujours_un_prix_de_reference(case: SignalCase) -> None:
    """Sans prix ecrit, la reference reste None : le moteur utilisera le marche."""
    signal = parse(case.text)
    if signal.has_entry:
        assert signal.reference_entry is not None
    else:
        assert signal.reference_entry is None
        assert signal.order_type is OrderType.MARKET


# ---------------------------------------------------------------------------
# Bruit : jamais de signal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("label", "text"), NOISE_MESSAGES, ids=_ids(NOISE_MESSAGES))
def test_le_bavardage_ne_produit_jamais_de_signal(label: str, text: str) -> None:
    signal = parse(text)
    assert signal.is_signal is False, label
    assert signal.direction is None or signal.entry_price is None
    assert signal.stop_loss is None
    assert signal.take_profits == []
    assert signal.confidence == 0.0


def test_une_opinion_de_marche_reste_sans_action() -> None:
    """CDC section 49 : "Gold looking good today" ne devient jamais BUY XAUUSD."""
    signal = parse("Gold looking good today.")
    assert signal.is_signal is False
    assert signal.direction is None


# ---------------------------------------------------------------------------
# Messages ambigus
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", AMBIGUOUS_MESSAGES, ids=_ids(AMBIGUOUS_MESSAGES))
def test_les_messages_ambigus_ne_sont_jamais_executables(case: AmbiguousCase) -> None:
    signal = validator.sanitize(parse(case.text))
    result = validator.validate(signal)

    assert signal.is_signal is case.expected_signal, case.label
    assert result.ok is False, case.label
    codes = {issue.code for issue in result.issues}
    assert set(case.issue_codes) <= codes, f"{case.label} : {codes}"


# ---------------------------------------------------------------------------
# Score de confiance (CDC section 50)
# ---------------------------------------------------------------------------

def test_confiance_maximale_pour_une_structure_parfaite() -> None:
    """Instrument, direction, type d'ordre, entree, SL et TP tous explicites."""
    signal = parse("XAUUSD BUY LIMIT 3340\nSL 3325\nTP 3370")
    assert signal.confidence == 1.0
    assert not signal.warnings


def test_confiance_plus_basse_sans_stop_loss() -> None:
    avec_sl = parse("XAUUSD BUY LIMIT 3340\nSL 3325\nTP 3370")
    sans_sl = parse("XAUUSD BUY LIMIT 3340\nTP 3370")
    assert sans_sl.confidence < avec_sl.confidence
    assert sans_sl.stop_loss is None
    assert sans_sl.confidence == pytest.approx(0.80)


def test_confiance_plus_basse_sans_take_profit() -> None:
    sans_tp = parse("XAUUSD BUY LIMIT 3340\nSL 3325")
    assert sans_tp.confidence == pytest.approx(0.85)
    assert sans_tp.take_profits == []


def test_confiance_minimale_pour_une_direction_seule() -> None:
    signal = parse("XAUUSD BUY LIMIT 3340")
    assert signal.confidence == pytest.approx(0.65)


def test_les_avertissements_font_baisser_la_confiance() -> None:
    """Un type d'ordre non precise coute 0.05 : le message reste lisible."""
    signal = parse("XAUUSD BUY 3340\nSL 3325\nTP 3370")
    assert "type_ordre_non_precise" in signal.warnings
    assert signal.confidence == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# Pieges numeriques
# ---------------------------------------------------------------------------

def test_un_tp_indexe_n_avale_jamais_la_partie_entiere_du_prix() -> None:
    """"TP 1.0840" vaut 1.0840, jamais 840 avec un index 1."""
    signal = parse("EURUSD BUY\nENTRY 1.0820\nSL 1.0790\nTP 1.0840")
    assert signal.take_profits == [1.0840]
    assert 840.0 not in signal.take_profits


def test_les_prix_a_cinq_decimales_sont_conserves() -> None:
    signal = parse("EURUSD SELL\nENTRY 1.08425\nSL 1.08725\nTP 1.07925")
    assert signal.entry_price == 1.08425
    assert signal.stop_loss == 1.08725
    assert signal.take_profits == [1.07925]


def test_un_index_explicite_reste_lisible_devant_un_prix_decimal() -> None:
    signal = parse("EURUSD BUY\nENTRY 1.0820\nSL 1.0790\nTP1 1.0840\nTP2 1.0870")
    assert signal.take_profits == [1.0840, 1.0870]


@pytest.mark.parametrize(
    ("text", "symbol", "entry"),
    [
        ("US30 SELL 44250\nSL 44400\nTP 43900", "US30", 44250.0),
        ("NAS100 BUY 20150\nSL 20050\nTP 20400", "NAS100", 20150.0),
        ("GER40 SELL 18250\nSL 18350\nTP 18050", "GER40", 18250.0),
    ],
)
def test_le_chiffre_du_nom_d_indice_n_est_pas_un_prix(text: str, symbol: str, entry: float) -> None:
    signal = parse(text)
    assert signal.symbol == symbol
    assert signal.entry_price == entry


def test_zone_d_entree_toujours_ordonnee() -> None:
    signal = parse("XAUUSD BUY 3320-3315\nSL 3300\nTP 3350")
    assert signal.entry_min == 3315.0
    assert signal.entry_max == 3320.0
    assert signal.entry_price is None
    assert signal.reference_entry == pytest.approx(3317.5)


def test_tp_indexes_contre_liste_de_cibles() -> None:
    indexes = parse("XAUUSD SELL 3350\nSL 3365\nTP1 3335\nTP2 3320\nTP3 3300")
    liste = parse("Sell gold now @ 3350\nstop 3365\ntargets 3335, 3320, 3300")
    assert indexes.take_profits == [3335.0, 3320.0, 3300.0]
    assert liste.take_profits == [3335.0, 3320.0, 3300.0]


def test_les_tp_indexes_sont_remis_dans_l_ordre_des_index() -> None:
    signal = parse("XAUUSD BUY 3320\nSL 3310\nTP3 3360\nTP1 3330\nTP2 3345")
    assert signal.take_profits == [3330.0, 3345.0, 3360.0]


def test_un_numero_d_objectif_seul_n_est_pas_un_prix() -> None:
    """"TP 1" designe l'objectif numero 1, pas un prix de 1.00."""
    signal = parse("XAUUSD BUY 3320\nSL 3310\nTP 1")
    assert signal.take_profits == []


def test_un_take_profit_absurde_est_ignore_avec_un_avertissement() -> None:
    signal = parse("XAUUSD BUY 3320\nSL 3310\nTP 120")
    assert signal.take_profits == []
    assert "take_profit_implausible_ignored" in signal.warnings


def test_un_stop_loss_absurde_est_ignore() -> None:
    signal = parse("XAUUSD BUY\nENTRY 3320\nSL 2\nTP 3350")
    assert signal.stop_loss is None
    assert "stop_loss_implausible_ignored" in signal.warnings


def test_buy_stop_n_est_pas_confondu_avec_un_stop_loss() -> None:
    signal = parse("XAUUSD BUY STOP 3340\nSL 3325\nTP 3370")
    assert signal.order_type is OrderType.BUY_STOP
    assert signal.entry_price == 3340.0
    assert signal.stop_loss == 3325.0


def test_un_message_vide_ne_produit_rien() -> None:
    signal = parse("")
    assert signal.is_signal is False
    assert signal.symbol is None
    assert signal.direction is None


def test_direction_sans_instrument_est_signalee() -> None:
    signal = parse("BUY NOW\nSL 3310\nTP 3330")
    assert signal.is_signal is False
    assert signal.direction is Direction.BUY
    assert signal.symbol is None
    assert "instrument_absent" in signal.warnings


def test_instrument_sans_direction_est_signale() -> None:
    signal = parse("XAUUSD 3320\nSL 3310\nTP 3330")
    assert signal.is_signal is False
    assert signal.symbol == "XAUUSD"
    assert signal.direction is None
    assert "direction_absente" in signal.warnings


def test_signature_de_format_renseignee_pour_l_apprentissage_de_canal() -> None:
    signal = parse("XAUUSD BUY\nENTRY 3320\nSL 3310\nTP1 3330\nTP2 3340")
    assert signal.format_signature == "BUY|ENTRY|SL|TP1|TP2"


def test_alias_de_canal_pris_en_compte() -> None:
    aliases = {"THE YELLOW ONE": "XAUUSD", "ZEDAX": "GER40"}
    signal = parse("ZEDAX BUY 18250\nSL 18150\nTP 18500", aliases)
    assert signal.symbol == "GER40"


def test_parse_symbol_only() -> None:
    assert parse_symbol_only("CLOSE GOLD NOW") == "XAUUSD"
    assert parse_symbol_only("GOLD") == "XAUUSD"
    assert parse_symbol_only("CLOSE NOW") is None
