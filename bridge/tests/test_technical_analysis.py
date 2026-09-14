"""Moteur d'analyse technique : indicateurs, structure, multi-timeframes.

Toutes les series sont construites a la main : aucun acces reseau, aucun
terminal MetaTrader, aucune donnee de marche reelle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from app.models.enums import Direction
from app.models.intelligence import Timeframe, TrendState
from app.services.mt5.interface import Candle
from app.services.technical_analysis import indicators, structure
from app.services.technical_analysis.engine import TechnicalAnalysis, TechnicalAnalysisEngine
from app.services.technical_analysis.multi_timeframe import (
    DEFAULT_PROFILE,
    SCALPING_PROFILE,
    STATE_ENTRY_CONFIRMATION,
    STATE_NO_DATA,
    STATE_NO_TRIGGER,
    STATE_PULLBACK,
    MultiTimeframeAnalyzer,
    TimeframeProfile,
    TimeframeRole,
    build_profile,
    profile_for,
)

BASE = datetime(2024, 1, 1, tzinfo=UTC)


def make_candle(index: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        time=BASE + timedelta(hours=index),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_volume=100,
    )


def from_closes(values: list[float], wick: float = 0.2) -> list[Candle]:
    """Bougies simples autour d'une serie de clotures."""
    candles: list[Candle] = []
    previous = values[0]
    for index, value in enumerate(values):
        candles.append(
            make_candle(
                index,
                previous,
                max(previous, value) + wick,
                min(previous, value) - wick,
                value,
            )
        )
        previous = value
    return candles


def zigzag(pivots: list[float], legs: int = 5) -> list[float]:
    """Serie de clotures passant par des pivots successifs."""
    values: list[float] = [pivots[0]]
    for start, end in pairwise(pivots):
        for step in range(1, legs + 1):
            values.append(start + (end - start) * step / legs)
    return values


# ---------------------------------------------------------------------------
# Indicateurs
# ---------------------------------------------------------------------------

def test_true_range_prend_le_gap_en_compte() -> None:
    candle = make_candle(1, 10.0, 11.0, 9.5, 10.5)
    assert indicators.true_range(10.0, candle) == pytest.approx(1.5)
    # Cloture precedente tres basse : le gap domine l'amplitude interne.
    assert indicators.true_range(5.0, candle) == pytest.approx(6.0)


def test_atr_est_la_moyenne_des_amplitudes() -> None:
    candles = [
        make_candle(0, 10.0, 11.0, 9.0, 10.0),
        make_candle(1, 10.0, 12.0, 10.0, 11.0),
        make_candle(2, 11.0, 13.0, 11.0, 12.0),
    ]
    assert indicators.atr(candles, period=2) == pytest.approx(2.0)


def test_atr_none_quand_historique_insuffisant() -> None:
    assert indicators.atr([make_candle(0, 1.0, 1.0, 1.0, 1.0)], period=14) is None
    assert indicators.atr([], period=2) is None


def test_rsi_hausse_continue_sature_a_cent() -> None:
    values = [float(100 + index) for index in range(40)]
    assert indicators.rsi(values, 14) == pytest.approx(100.0)


def test_rsi_baisse_continue_tend_vers_zero() -> None:
    values = [float(200 - index) for index in range(40)]
    assert indicators.rsi(values, 14) == pytest.approx(0.0, abs=0.001)


def test_rsi_none_si_serie_trop_courte() -> None:
    assert indicators.rsi([1.0, 2.0, 3.0], 14) is None


def test_moyennes_mobiles() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert indicators.sma(values, 5) == pytest.approx(3.0)
    assert indicators.sma(values, 9) is None
    assert indicators.ema(values, 5) == pytest.approx(3.0)
    assert indicators.ema([1.0, 2.0], 5) is None


def test_momentum_est_une_variation_en_pourcentage() -> None:
    values = [100.0, 101.0, 102.0, 103.0, 110.0]
    assert indicators.momentum(values, 4) == pytest.approx(10.0)
    assert indicators.momentum(values, 10) is None


def test_efficiency_ratio_distingue_ligne_droite_et_surplace() -> None:
    droite = [float(index) for index in range(30)]
    assert indicators.efficiency_ratio(droite, 20) == pytest.approx(1.0)
    surplace = [100.0 + (1.0 if index % 2 else -1.0) for index in range(30)]
    assert indicators.efficiency_ratio(surplace, 20) == pytest.approx(0.0, abs=0.06)


def test_slope_et_volatilite() -> None:
    values = [float(index) for index in range(10)]
    assert indicators.slope(values) == pytest.approx(1.0)
    assert indicators.slope([1.0]) is None
    assert indicators.volatility(values, 5) is not None
    assert indicators.volatility(values, 50) is None


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_find_swings_detecte_sommet_et_creux() -> None:
    candles = from_closes(zigzag([100.0, 110.0, 102.0, 118.0], legs=5))
    swings = structure.find_swings(candles, strength=2)
    kinds = [swing.kind for swing in swings]
    assert "HIGH" in kinds
    assert "LOW" in kinds
    highs = [swing for swing in swings if swing.kind == "HIGH"]
    assert highs[0].price == pytest.approx(110.2, abs=0.3)


def test_read_structure_haussiere() -> None:
    candles = from_closes(zigzag([100.0, 112.0, 106.0, 124.0, 118.0, 136.0], legs=5))
    reading = structure.read_structure(structure.find_swings(candles, 2))
    assert reading.label == structure.STRUCTURE_BULLISH
    assert reading.bullish is True
    assert reading.high_labels[-1] == "HH"
    assert reading.low_labels[-1] == "HL"


def test_read_structure_baissiere() -> None:
    candles = from_closes(zigzag([140.0, 128.0, 134.0, 116.0, 122.0, 104.0], legs=5))
    reading = structure.read_structure(structure.find_swings(candles, 2))
    assert reading.label == structure.STRUCTURE_BEARISH
    assert reading.bearish is True


def test_detect_break_qualifie_un_change_of_character() -> None:
    # Structure baissiere, puis cassure du dernier sommet vers le haut.
    values = zigzag([140.0, 128.0, 134.0, 116.0, 122.0, 108.0, 130.0], legs=5)
    candles = from_closes(values)
    swings = structure.find_swings(candles, 2)
    reading = structure.read_structure(swings)
    event = structure.detect_break(candles, swings, reading)
    assert event is not None
    assert event.direction == "UP"
    assert event.kind == "CHOCH"


def test_levels_around_regroupe_les_niveaux() -> None:
    swings = [
        structure.SwingPoint(0, BASE, 100.0, "LOW"),
        structure.SwingPoint(5, BASE, 100.1, "LOW"),
        structure.SwingPoint(10, BASE, 120.0, "HIGH"),
    ]
    levels = structure.levels_around(swings, price=110.0, tolerance=1.0)
    assert levels.support == pytest.approx(100.05)
    assert levels.resistance == pytest.approx(120.0)
    assert levels.supports[0].touches == 2


def test_levels_around_sans_swing() -> None:
    levels = structure.levels_around([], price=100.0)
    assert levels.support is None
    assert levels.resistance is None


def test_read_range_reconnait_le_surplace() -> None:
    values = [100.0 + (1.0 if index % 2 else -1.0) for index in range(60)]
    reading = structure.read_range(from_closes(values), lookback=40)
    assert reading.is_range is True
    assert reading.high is not None and reading.low is not None
    assert 0.0 <= (reading.position or 0.0) <= 1.0


def test_read_range_rejette_une_tendance() -> None:
    reading = structure.read_range(from_closes([float(100 + index) for index in range(60)]))
    assert reading.is_range is False


def test_detect_breakout_haussier() -> None:
    values = [100.0 + (0.5 if index % 2 else -0.5) for index in range(60)]
    values += [120.0, 121.0]
    candles = from_closes(values)
    atr_value = indicators.atr(candles, 14)
    assert structure.detect_breakout(candles, atr_value, lookback=40) == "UP"


def test_detect_breakout_none_sans_atr() -> None:
    candles = from_closes([float(100 + index) for index in range(60)])
    assert structure.detect_breakout(candles, None) is None


def test_detect_pullback_mesure_la_profondeur() -> None:
    candles = from_closes(zigzag([110.0, 100.0, 130.0, 118.0], legs=6))
    swings = structure.find_swings(candles, 2)
    reading = structure.read_structure(swings)
    depth = structure.detect_pullback(candles, reading, bullish=True)
    assert depth is not None
    assert depth == pytest.approx(0.4, abs=0.02)
    # Aucun repli baissier : l'impulsion mesuree est haussiere.
    assert structure.detect_pullback(candles, reading, bullish=False) is None


# ---------------------------------------------------------------------------
# Moteur
# ---------------------------------------------------------------------------

def test_analyse_serie_vide_ne_leve_pas() -> None:
    result = TechnicalAnalysisEngine().analyse("XAUUSD", Timeframe.H1, [])
    assert result.usable is False
    assert result.last_close is None
    assert result.atr is None
    assert result.reasons


def test_analyse_tendance_haussiere() -> None:
    candles = from_closes([100.0 + index * 0.8 for index in range(120)])
    result = TechnicalAnalysisEngine().analyse("EURUSD", Timeframe.H1, candles)
    assert result.trend is TrendState.BULLISH
    assert result.trend_score >= 2
    assert result.usable is True
    assert result.atr is not None and result.atr > 0


def test_analyse_tendance_baissiere() -> None:
    candles = from_closes([200.0 - index * 0.8 for index in range(120)])
    result = TechnicalAnalysisEngine().analyse("EURUSD", Timeframe.H1, candles)
    assert result.trend is TrendState.BEARISH
    assert result.trend_score <= -2


def test_stop_et_ratio_risque_rendement() -> None:
    candles = from_closes(zigzag([100.0, 120.0, 110.0, 135.0, 126.0, 150.0, 140.0], legs=10))
    result = TechnicalAnalysisEngine(slow_period=30).analyse("XAUUSD", Timeframe.H1, candles)
    stop = result.stop_loss_hint(Direction.BUY)
    assert stop is not None
    assert stop < (result.last_close or 0.0)
    distance = result.stop_distance(Direction.BUY)
    assert distance is not None and distance > 0
    ratio = result.risk_reward(Direction.BUY)
    # Une resistance existe au-dessus : le ratio est calculable.
    assert ratio is None or ratio > 0


def test_risque_rendement_none_sans_niveau_oppose() -> None:
    result = TechnicalAnalysis(symbol="XAUUSD", timeframe=Timeframe.H1, last_close=100.0, atr=1.0)
    assert result.target_hint(Direction.BUY) is None
    assert result.risk_reward(Direction.BUY) is None
    assert result.stop_distance(Direction.BUY) == pytest.approx(1.5)


def test_to_dict_expose_les_cles_attendues() -> None:
    candles = from_closes([100.0 + index * 0.4 for index in range(120)])
    payload = TechnicalAnalysisEngine().analyse("XAUUSD", Timeframe.H1, candles).to_dict()
    for key in ("atr", "rsi", "trend", "structure", "levels", "range", "buy", "sell", "reasons"):
        assert key in payload
    assert payload["timeframe"] == "H1"


# ---------------------------------------------------------------------------
# Multi-timeframes
# ---------------------------------------------------------------------------

def analysis(
    timeframe: Timeframe, trend: TrendState, **extra: object
) -> TechnicalAnalysis:
    """Analyse fabriquee de toutes pieces, pour tester la seule consolidation."""
    item = TechnicalAnalysis(
        symbol="XAUUSD", timeframe=timeframe, last_close=100.0, atr=1.0, candles_used=200
    )
    item.trend = trend
    for key, value in extra.items():
        setattr(item, key, value)
    return item


def test_profil_par_defaut_repartit_les_roles() -> None:
    assert DEFAULT_PROFILE.roles[Timeframe.D1] is TimeframeRole.CONTEXT
    assert DEFAULT_PROFILE.roles[Timeframe.H1] is TimeframeRole.STRUCTURE
    assert DEFAULT_PROFILE.roles[Timeframe.M15] is TimeframeRole.TRIGGER
    assert DEFAULT_PROFILE.of_role(TimeframeRole.CONTEXT) == [Timeframe.D1, Timeframe.H4]


def test_profile_for_retombe_sur_le_defaut() -> None:
    assert profile_for("scalping") is SCALPING_PROFILE
    assert profile_for("inconnue") is DEFAULT_PROFILE
    assert profile_for(None) is DEFAULT_PROFILE


def test_build_profile_ignore_les_entrees_invalides() -> None:
    profile = build_profile("maison", {"H4": "CONTEXT", "ZZ": "CONTEXT", "H1": "INEXISTANT"})
    assert profile.roles == {Timeframe.H4: TimeframeRole.CONTEXT}


def test_combine_produit_un_etat_par_timeframe() -> None:
    profile = TimeframeProfile(
        name="test",
        roles={
            Timeframe.D1: TimeframeRole.CONTEXT,
            Timeframe.H4: TimeframeRole.CONTEXT,
            Timeframe.H1: TimeframeRole.STRUCTURE,
            Timeframe.M15: TimeframeRole.TRIGGER,
            Timeframe.M5: TimeframeRole.CONFIRMATION,
        },
    )
    analyses = {
        Timeframe.D1: analysis(Timeframe.D1, TrendState.BULLISH),
        Timeframe.H4: analysis(Timeframe.H4, TrendState.BULLISH),
        Timeframe.H1: analysis(Timeframe.H1, TrendState.BULLISH, pullback=0.4),
        Timeframe.M15: analysis(
            Timeframe.M15,
            TrendState.NEUTRAL,
            break_event=structure.BreakEvent("UP", "CHOCH", 99.0, 10, BASE),
        ),
        Timeframe.M5: analysis(Timeframe.M5, TrendState.BULLISH, momentum=0.8),
    }
    view = MultiTimeframeAnalyzer().combine("XAUUSD", profile, analyses)
    assert view.bias is TrendState.BULLISH
    assert view.states() == {
        "D1": "BULLISH",
        "H4": "BULLISH",
        "H1": STATE_PULLBACK,
        "M15": "REVERSAL_TRIGGER",
        "M5": STATE_ENTRY_CONFIRMATION,
    }
    assert view.alignment == pytest.approx(1.0)
    assert view.conflicts == []


def test_combine_signale_les_conflits_et_l_absence_de_donnees() -> None:
    profile = TimeframeProfile(
        name="test",
        roles={
            Timeframe.D1: TimeframeRole.CONTEXT,
            Timeframe.H1: TimeframeRole.STRUCTURE,
            Timeframe.M15: TimeframeRole.TRIGGER,
        },
    )
    analyses = {
        Timeframe.D1: analysis(Timeframe.D1, TrendState.BULLISH),
        Timeframe.H1: analysis(Timeframe.H1, TrendState.BEARISH),
        Timeframe.M15: TechnicalAnalysis(symbol="XAUUSD", timeframe=Timeframe.M15),
    }
    view = MultiTimeframeAnalyzer().combine("XAUUSD", profile, analyses)
    assert view.bias is TrendState.BULLISH
    assert view.states()["M15"] == STATE_NO_DATA
    assert view.alignment == pytest.approx(0.5)
    assert any("H1" in message for message in view.conflicts)
    assert view.trigger is None


def test_combine_sans_biais_ne_declenche_rien() -> None:
    profile = TimeframeProfile(
        name="test",
        roles={
            Timeframe.D1: TimeframeRole.CONTEXT,
            Timeframe.H4: TimeframeRole.CONTEXT,
            Timeframe.M15: TimeframeRole.TRIGGER,
            Timeframe.M5: TimeframeRole.CONFIRMATION,
        },
    )
    analyses = {
        Timeframe.D1: analysis(Timeframe.D1, TrendState.BULLISH),
        Timeframe.H4: analysis(Timeframe.H4, TrendState.BEARISH),
        Timeframe.M15: analysis(Timeframe.M15, TrendState.NEUTRAL),
        Timeframe.M5: analysis(Timeframe.M5, TrendState.NEUTRAL, momentum=1.0),
    }
    view = MultiTimeframeAnalyzer().combine("XAUUSD", profile, analyses)
    assert view.bias is TrendState.NEUTRAL
    assert view.alignment == 0.0
    assert view.states()["M15"] == STATE_NO_TRIGGER
    assert view.states()["M5"] == "WAIT"
    assert view.conflicts
