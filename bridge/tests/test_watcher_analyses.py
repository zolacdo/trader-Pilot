"""Analyses deterministes du Market Watcher : volatilite, volume, price action, liquidite.

Toutes les series sont construites a la main. Aucun terminal MetaTrader,
aucune donnee de marche reelle, aucun acces reseau.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.mt5.interface import Candle
from app.services.technical_analysis.structure import find_swings
from app.watcher.analysis.liquidity import read_liquidity
from app.watcher.analysis.price_action import read_price_action
from app.watcher.analysis.volatility import read_volatility
from app.watcher.analysis.volume import read_volume
from app.watcher.models import VolatilityLevel, VolumeKind

BASE = datetime(2024, 1, 1, tzinfo=UTC)


def candle(
    index: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: int = 100,
) -> Candle:
    return Candle(
        time=BASE + timedelta(minutes=index),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_volume=volume,
    )


def steady(count: int, amplitude: float = 1.0, volume: int = 100) -> list[Candle]:
    """Serie parfaitement reguliere : amplitude constante, prix immobile."""
    return [
        candle(index, 100.0, 100.0 + amplitude, 100.0 - amplitude, 100.0, volume)
        for index in range(count)
    ]


# ---------------------------------------------------------------------------
# Volatilite (CDC3 section 11)
# ---------------------------------------------------------------------------
class TestVolatilite:
    def test_historique_trop_court_reste_inconnu(self) -> None:
        """Sans reference historique, aucune classification n'est inventee."""
        reading = read_volatility(steady(10))
        assert reading.level is VolatilityLevel.UNKNOWN
        assert reading.ratio_to_reference is None

    def test_amplitude_constante_donne_normal(self) -> None:
        reading = read_volatility(steady(120))
        assert reading.level is VolatilityLevel.NORMAL
        assert reading.ratio_to_reference == 1.0

    def test_explosion_recente_donne_extreme(self) -> None:
        """Une amplitude multipliee par dix sur la fin doit sortir du normal."""
        candles = steady(120)
        for index in range(100, 120):
            candles[index] = candle(index, 100.0, 110.0, 90.0, 100.0)
        reading = read_volatility(candles)
        assert reading.level is VolatilityLevel.EXTREME
        assert reading.extreme is True

    def test_accalmie_donne_faible(self) -> None:
        candles = steady(120)
        for index in range(100, 120):
            candles[index] = candle(index, 100.0, 100.1, 99.9, 100.0)
        reading = read_volatility(candles)
        assert reading.level is VolatilityLevel.LOW

    def test_serie_vide_ne_leve_pas(self) -> None:
        assert read_volatility([]).level is VolatilityLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Volume (CDC3 section 12)
# ---------------------------------------------------------------------------
class TestVolume:
    def test_le_volume_est_declare_comme_tick_volume(self) -> None:
        """MetaTrader ne fournit ici que du tick volume : on ne pretend pas autre chose."""
        reading = read_volume(steady(40))
        assert reading.kind is VolumeKind.TICK
        assert reading.real is False

    def test_echantillon_trop_court_reste_inconnu(self) -> None:
        reading = read_volume(steady(5))
        assert reading.kind is VolumeKind.UNKNOWN
        assert reading.ratio is None

    def test_activite_soutenue_detectee(self) -> None:
        candles = steady(40)
        candles[-1] = candle(39, 100.0, 101.0, 99.0, 100.0, volume=500)
        reading = read_volume(candles)
        assert reading.trend == "RISING"
        assert reading.ratio is not None and reading.ratio >= 1.5

    def test_cassure_sans_volume_est_signalee(self) -> None:
        candles = steady(40)
        reading = read_volume(candles, breakout="UP")
        assert reading.supports_breakout is False
        assert "pas accompagnee" in reading.detail

    def test_cassure_avec_volume_est_signalee(self) -> None:
        candles = steady(40)
        candles[-1] = candle(39, 100.0, 101.0, 99.0, 100.0, volume=400)
        reading = read_volume(candles, breakout="UP")
        assert reading.supports_breakout is True


# ---------------------------------------------------------------------------
# Price action (CDC3 section 9)
# ---------------------------------------------------------------------------
class TestPriceAction:
    def test_historique_trop_court(self) -> None:
        assert read_price_action(steady(3)).bias == "NEUTRAL"

    def test_engulfing_haussier(self) -> None:
        candles = steady(20)
        candles[-2] = candle(18, 101.0, 101.2, 99.8, 100.0)  # baissiere
        candles[-1] = candle(19, 99.5, 102.0, 99.4, 101.5)  # engloutit la precedente
        reading = read_price_action(candles)
        assert "engulfing haussier" in reading.patterns
        assert reading.bias == "BULLISH"

    def test_pin_bar_baissier(self) -> None:
        candles = steady(20)
        candles[-1] = candle(19, 100.0, 106.0, 99.8, 100.2)
        reading = read_price_action(candles)
        assert any("pin bar baissier" in pattern for pattern in reading.patterns)
        assert reading.score < 0

    def test_doji_reconnu(self) -> None:
        candles = steady(20)
        candles[-1] = candle(19, 100.0, 102.0, 98.0, 100.0)
        reading = read_price_action(candles)
        assert "doji" in reading.patterns

    def test_inside_bar_reconnue(self) -> None:
        candles = steady(20)
        candles[-2] = candle(18, 100.0, 105.0, 95.0, 100.0)
        candles[-1] = candle(19, 100.0, 101.0, 99.0, 100.5)
        assert "inside bar" in read_price_action(candles).patterns

    def test_compression_detectee(self) -> None:
        candles = steady(20, amplitude=2.0)
        for index in (17, 18, 19):
            candles[index] = candle(index, 100.0, 100.2, 99.8, 100.0)
        reading = read_price_action(candles)
        assert reading.compression is True
        assert reading.pressure == "INDECISION"

    def test_essoufflement_sur_grande_bougie_sans_corps(self) -> None:
        """Une grande amplitude rendue au marche se lit comme un essoufflement."""
        candles = steady(20, amplitude=0.5)
        candles[-1] = candle(19, 100.0, 105.0, 95.0, 100.1)
        assert read_price_action(candles).pressure == "ESSOUFFLEMENT"


# ---------------------------------------------------------------------------
# Liquidite (CDC3 section 13)
# ---------------------------------------------------------------------------
class TestLiquidite:
    def _serie_avec_sommets_egaux(self) -> list[Candle]:
        """Deux sommets au meme prix, puis une meche au-dessus et un retour."""
        candles: list[Candle] = []
        for index in range(40):
            candles.append(candle(index, 100.0, 101.0, 99.0, 100.0))
        # Deux sommets identiques a 105, separes par un creux.
        candles[10] = candle(10, 100.0, 105.0, 99.0, 104.0)
        candles[20] = candle(20, 100.0, 105.0, 99.0, 104.0)
        candles[15] = candle(15, 100.0, 101.0, 95.0, 96.0)
        # Meche au-dessus du niveau, cloture nettement en dessous.
        candles[38] = candle(38, 104.0, 108.0, 103.0, 103.5)
        candles[39] = candle(39, 103.5, 104.0, 102.0, 102.5)
        return candles

    def test_sommets_egaux_et_balayage(self) -> None:
        candles = self._serie_avec_sommets_egaux()
        swings = find_swings(candles, strength=2)
        reading = read_liquidity(candles, swings, atr=2.0)
        assert reading.equal_highs, "les deux sommets a 105 doivent etre regroupes"
        assert reading.sweep == "HIGH"
        assert reading.bias == "BEARISH"

    def test_sans_atr_aucune_lecture(self) -> None:
        candles = self._serie_avec_sommets_egaux()
        reading = read_liquidity(candles, find_swings(candles, 2), atr=None)
        assert reading.sweep is None
        assert reading.bias == "NEUTRAL"

    def test_serie_vide_ne_leve_pas(self) -> None:
        assert read_liquidity([], [], atr=1.0).sweep is None
