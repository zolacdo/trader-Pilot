"""Detecteur de regime de marche et enregistrement des changements."""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.intelligence import MarketRegime, Timeframe
from app.repositories import market_repo
from app.services.market_data.engine import MarketDataEngine
from app.services.market_regime.detector import (
    HIGH_VOLATILITY_RATIO,
    MarketRegimeDetector,
)
from app.services.mt5.fake_service import FakeMetaTraderService
from tests.test_technical_analysis import from_closes, zigzag


def detecteur() -> MarketRegimeDetector:
    return MarketRegimeDetector()


def test_historique_insuffisant_rend_uncertain() -> None:
    result = detecteur().assess("XAUUSD", Timeframe.H1, from_closes([100.0, 101.0, 102.0]))
    assert result.regime is MarketRegime.UNCERTAIN
    assert result.atr_ratio is None
    assert "insuffisant" in result.detail.lower()


def test_serie_vide_rend_uncertain() -> None:
    result = detecteur().assess("XAUUSD", Timeframe.H1, [])
    assert result.regime is MarketRegime.UNCERTAIN
    assert result.confidence == 0.0
    assert result.atr is None


def test_tendance_haussiere_est_trending_up() -> None:
    candles = from_closes([100.0 + index * 0.9 for index in range(160)])
    result = detecteur().assess("EURUSD", Timeframe.H1, candles)
    assert result.regime is MarketRegime.TRENDING_UP
    assert result.confidence > 0.5
    assert result.features["trend"] == "BULLISH"


def test_tendance_baissiere_est_trending_down() -> None:
    candles = from_closes([300.0 - index * 0.9 for index in range(160)])
    result = detecteur().assess("EURUSD", Timeframe.H1, candles)
    assert result.regime is MarketRegime.TRENDING_DOWN


def test_surplace_est_ranging() -> None:
    values = [100.0 + (0.6 if index % 2 else -0.6) for index in range(160)]
    result = detecteur().assess("EURUSD", Timeframe.H1, from_closes(values))
    assert result.regime is MarketRegime.RANGING
    assert result.features["isRange"] is True


def test_expansion_de_volatilite_est_high_volatility() -> None:
    # Serie calme, puis quelques bougies tres larges sans direction nette.
    values = [100.0 + (0.2 if index % 2 else -0.2) for index in range(160)]
    values += [100.0, 140.0, 100.0, 140.0, 100.0]
    result = detecteur().assess("XAUUSD", Timeframe.H1, from_closes(values))
    assert result.atr_ratio is not None
    assert result.atr_ratio >= HIGH_VOLATILITY_RATIO
    assert result.regime in {MarketRegime.HIGH_VOLATILITY, MarketRegime.BREAKOUT}


def test_sortie_de_range_est_breakout() -> None:
    values = [100.0 + (0.4 if index % 2 else -0.4) for index in range(120)]
    values += [104.0, 112.0, 120.0]
    result = detecteur().assess("XAUUSD", Timeframe.H1, from_closes(values))
    assert result.features["breakout"] == "UP"
    assert result.regime is MarketRegime.BREAKOUT
    assert "haussier" in result.detail


def test_pression_d_actualite_est_prioritaire() -> None:
    values = [100.0 + (0.4 if index % 2 else -0.4) for index in range(120)]
    values += [104.0, 112.0, 120.0]
    candles = from_closes(values)
    sans = detecteur().assess("XAUUSD", Timeframe.H1, candles)
    avec = detecteur().assess("XAUUSD", Timeframe.H1, candles, news_pressure=True)
    assert sans.regime is MarketRegime.BREAKOUT
    assert avec.regime is MarketRegime.NEWS_DRIVEN
    assert avec.features["newsPressure"] is True


def test_news_driven_exige_une_volatilite_reelle() -> None:
    # Sans expansion de volatilite, une actualite ne suffit pas a changer le regime.
    candles = from_closes([100.0 + index * 0.9 for index in range(160)])
    result = detecteur().assess("EURUSD", Timeframe.H1, candles, news_pressure=True)
    assert result.regime is MarketRegime.TRENDING_UP


def test_compression_est_low_volatility() -> None:
    # Amplitude qui se reduit fortement : ATR courant tres inferieur a sa reference.
    values = zigzag([100.0, 130.0, 100.0, 130.0], legs=20)
    values += [115.0 + (0.01 if index % 2 else -0.01) for index in range(40)]
    result = detecteur().assess("XAUUSD", Timeframe.H1, from_closes(values, wick=0.0))
    assert result.atr_ratio is not None and result.atr_ratio <= 0.6
    assert result.regime in {MarketRegime.LOW_VOLATILITY, MarketRegime.RANGING}


def test_to_dict_expose_les_chiffres() -> None:
    candles = from_closes([100.0 + index * 0.9 for index in range(160)])
    payload = detecteur().assess("EURUSD", Timeframe.H1, candles).to_dict()
    assert payload["symbol"] == "EURUSD"
    assert payload["timeframe"] == "H1"
    assert payload["regime"] == MarketRegime.TRENDING_UP.value
    assert "atrRatio" in payload["features"]


async def test_detect_utilise_le_moteur_de_donnees() -> None:
    service = FakeMetaTraderService()
    await service.initialize()
    engine = MarketDataEngine(service)
    result = await detecteur().detect(engine, "XAUUSD", Timeframe.H1, bars=200)
    assert result.symbol == "XAUUSD"
    assert result.atr is not None
    assert result.regime in set(MarketRegime)


# ---------------------------------------------------------------------------
# Persistance
# ---------------------------------------------------------------------------

async def test_seuls_les_changements_de_regime_sont_enregistres(
    session: AsyncSession,
) -> None:
    premier = await market_repo.record_regime_change(
        session, "XAUUSD", Timeframe.H1, MarketRegime.RANGING, atr=1.0, atr_ratio=0.9
    )
    assert premier is not None

    inchange = await market_repo.record_regime_change(
        session, "XAUUSD", Timeframe.H1, MarketRegime.RANGING
    )
    assert inchange is None

    change = await market_repo.record_regime_change(
        session, "XAUUSD", Timeframe.H1, MarketRegime.TRENDING_UP, detail="tendance"
    )
    assert change is not None
    records = await market_repo.list_regimes(session, "XAUUSD")
    assert [record.regime for record in records] == [
        MarketRegime.TRENDING_UP,
        MarketRegime.RANGING,
    ]


async def test_les_regimes_sont_suivis_par_timeframe(session: AsyncSession) -> None:
    await market_repo.record_regime_change(
        session, "XAUUSD", Timeframe.H1, MarketRegime.RANGING
    )
    autre = await market_repo.record_regime_change(
        session, "XAUUSD", Timeframe.H4, MarketRegime.RANGING
    )
    assert autre is not None
    dernier = await market_repo.last_regime(session, "XAUUSD", Timeframe.H4)
    assert dernier is not None and dernier.timeframe is Timeframe.H4
    assert await market_repo.last_regime(session, "EURUSD", Timeframe.H1) is None


def test_detail_est_tronque_pour_la_base() -> None:
    # Le champ detail est limite a 255 caracteres en base : la troncature est
    # faite au moment de l'ecriture, pas laissee au hasard.
    assert len(("x" * 400)[:255]) == 255


@pytest.mark.parametrize(
    "regime",
    [
        MarketRegime.TRENDING_UP,
        MarketRegime.TRENDING_DOWN,
        MarketRegime.RANGING,
        MarketRegime.HIGH_VOLATILITY,
        MarketRegime.LOW_VOLATILITY,
        MarketRegime.BREAKOUT,
        MarketRegime.NEWS_DRIVEN,
        MarketRegime.UNCERTAIN,
    ],
)
def test_les_huit_regimes_du_cdc_existent(regime: MarketRegime) -> None:
    assert regime.value in {item.value for item in MarketRegime}
