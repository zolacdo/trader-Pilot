"""Moteur cross-market : correlations calculees et exposition agregee.

Aucune correlation n'est attendue en dur : les tests verifient que les valeurs
proviennent bien des bougies fournies, et qu'une mesure impossible rend None.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import Direction, ExecutionMode, PositionState
from app.models.trading import TradeRecord
from app.repositories import pattern_repo
from app.services.cross_market import (
    CrossMarketAnalyzer,
    ExposureLeg,
    aggregate_currency_exposure,
    correlation,
    correlation_matrix,
    evaluate_correlated_exposure,
    pearson,
    split_symbol,
)
from app.services.cross_market.analyzer import causal_correlation_feature
from app.services.cross_market.correlation import MIN_OBSERVATIONS, compare_windows
from app.services.historical_patterns import MarketHistory, StaticCandleProvider
from app.services.mt5.interface import Candle
from tests.test_historical_patterns import ORIGIN, make_candles

PREFIX = "/api/v1"


def mirrored(candles: list[Candle], invert: bool = False, base: float = 2.0) -> list[Candle]:
    """Serie construite a partir d'une autre : correlation +1 ou -1 exacte."""
    sign = -1.0 if invert else 1.0
    result: list[Candle] = []
    price = base
    previous = candles[0].close
    for candle in candles[1:]:
        change = (candle.close - previous) / previous
        close = price * (1 + sign * change)
        result.append(
            Candle(
                time=candle.time,
                open=price,
                high=max(price, close) * 1.0001,
                low=min(price, close) * 0.9999,
                close=close,
                tick_volume=100,
            )
        )
        price = close
        previous = candle.close
    return result


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def test_correlation_parfaite_et_inverse() -> None:
    base = make_candles(120, seed=3)
    assert correlation(base[1:], mirrored(base)) == pytest.approx(1.0, abs=1e-6)
    assert correlation(base[1:], mirrored(base, invert=True)) == pytest.approx(-1.0, abs=1e-6)


def test_correlation_none_si_trop_peu_d_observations() -> None:
    court = make_candles(MIN_OBSERVATIONS - 5, seed=4)
    assert correlation(court, mirrored(court)) is None


def test_correlation_none_sans_variance() -> None:
    plat = [
        Candle(time=ORIGIN + timedelta(hours=index), open=1.0, high=1.0, low=1.0, close=1.0)
        for index in range(60)
    ]
    autre = make_candles(60, seed=5)
    assert pearson([0.0] * 60, [1.0] * 60) is None
    assert correlation(plat, autre) is None


def test_matrice_symetrique_et_sans_diagonale() -> None:
    base = make_candles(150, seed=6)
    series = {
        "EURUSD": base[1:],
        "GBPUSD": mirrored(base),
        "USDCHF": mirrored(base, invert=True),
    }
    matrix = correlation_matrix(series)
    assert matrix["EURUSD"]["GBPUSD"] == matrix["GBPUSD"]["EURUSD"]
    assert "EURUSD" not in matrix["EURUSD"]
    assert matrix["EURUSD"]["USDCHF"] < 0


def test_comparaison_recente_et_historique() -> None:
    base = make_candles(300, seed=11)
    series = {"EURUSD": base[1:], "GBPUSD": mirrored(base)}
    pairs = compare_windows(series, recent_bars=60, historical_bars=250)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.recent is not None
    assert pair.historical is not None
    assert pair.drift is not None
    assert pair.to_dict()["observations"] > 0


# ---------------------------------------------------------------------------
# Decomposition des symboles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("EURUSD", ("EUR", "USD")),
        ("USDCHF", ("USD", "CHF")),
        ("XAUUSD", ("XAU", "USD")),
        ("EURUSDm", ("EUR", "USD")),
        ("US30", None),
        ("NAS100", None),
    ],
)
def test_decomposition_des_symboles(symbol: str, expected: tuple[str, str] | None) -> None:
    assert split_symbol(symbol) == expected


# ---------------------------------------------------------------------------
# Exposition agregee
# ---------------------------------------------------------------------------

def test_exposition_contre_le_dollar_est_agregee() -> None:
    """L'exemple du CDC2 : trois positions, un seul pari contre l'USD."""
    legs = [
        ExposureLeg("EURUSD", Direction.BUY),
        ExposureLeg("GBPUSD", Direction.BUY),
        ExposureLeg("USDCHF", Direction.SELL),
    ]
    exposures, unparsed = aggregate_currency_exposure(legs)
    usd = next(item for item in exposures if item.currency == "USD")
    assert usd.net == pytest.approx(-3.0)
    assert usd.gross == pytest.approx(3.0)
    assert unparsed == []
    assert sorted(usd.symbols) == ["EURUSD", "GBPUSD", "USDCHF"]


def test_depassement_signale_en_francais() -> None:
    legs = [
        ExposureLeg("EURUSD", Direction.BUY),
        ExposureLeg("GBPUSD", Direction.BUY),
        ExposureLeg("USDCHF", Direction.SELL),
    ]
    strict = evaluate_correlated_exposure(legs, max_currency_exposure=2.0)
    assert strict.overexposed is True
    assert any("USD" in message for message in strict.breaches)
    assert any("agrégée" in message for message in strict.breaches)
    assert strict.dominant is not None and strict.dominant.currency == "USD"

    large = evaluate_correlated_exposure(legs, max_currency_exposure=5.0)
    assert large.overexposed is False
    assert large.breaches == []


def test_positions_opposees_se_compensent() -> None:
    legs = [
        ExposureLeg("EURUSD", Direction.BUY),
        ExposureLeg("EURUSD", Direction.SELL),
    ]
    assessment = evaluate_correlated_exposure(legs, max_currency_exposure=0.5)
    assert assessment.exposure_for("USD") == pytest.approx(0.0)
    assert assessment.overexposed is False


def test_groupes_correles_detectes_avec_les_correlations_mesurees() -> None:
    correlations = {"EURUSD": {"GBPUSD": 0.92}, "GBPUSD": {"EURUSD": 0.92}}
    memes = [ExposureLeg("EURUSD", Direction.BUY), ExposureLeg("GBPUSD", Direction.BUY)]
    opposes = [ExposureLeg("EURUSD", Direction.BUY), ExposureLeg("GBPUSD", Direction.SELL)]

    groupes = evaluate_correlated_exposure(memes, correlations=correlations).clusters
    assert len(groupes) == 1
    assert groupes[0].symbols == ["EURUSD", "GBPUSD"]

    assert evaluate_correlated_exposure(opposes, correlations=correlations).clusters == []


def test_sans_correlation_fournie_aucun_groupe_invente() -> None:
    legs = [ExposureLeg("EURUSD", Direction.BUY), ExposureLeg("GBPUSD", Direction.BUY)]
    assert evaluate_correlated_exposure(legs).clusters == []


def test_symbole_non_decompose_reste_signale() -> None:
    legs = [ExposureLeg("US30", Direction.BUY, weight=3.0)]
    assessment = evaluate_correlated_exposure(legs, max_currency_exposure=1.0)
    assert assessment.unparsed_symbols == ["US30"]
    assert assessment.exposure_for("US30") == pytest.approx(3.0)


def test_serialisation_de_l_exposition() -> None:
    legs = [ExposureLeg("EURUSD", Direction.BUY, weight=1.5)]
    payload = evaluate_correlated_exposure(legs).to_dict()
    assert payload["legs"] == 1
    assert payload["limits"]["maxCurrencyExposure"] == 2.0
    assert payload["dominant"]["direction"] in {"LONG", "SHORT", "FLAT"}


# ---------------------------------------------------------------------------
# Analyseur
# ---------------------------------------------------------------------------

async def test_analyseur_calcule_les_correlations() -> None:
    base = make_candles(300, seed=13)
    provider = StaticCandleProvider()
    provider.add("EURUSD", "H1", base[1:])
    provider.add("GBPUSD", "H1", mirrored(base))

    analyzer = CrossMarketAnalyzer(provider, recent_bars=60, historical_bars=250)
    report = await analyzer.analyse(["EURUSD", "GBPUSD", "XAUUSD"], end=base[-1].time)

    assert report.symbols == ["EURUSD", "GBPUSD"]
    assert report.unavailable == ["XAUUSD"]
    assert report.recent_matrix["EURUSD"]["GBPUSD"] == pytest.approx(1.0, abs=1e-6)
    payload = report.to_dict()
    assert payload["note"]
    assert payload["strongPairs"]


async def test_analyseur_produit_l_exposition() -> None:
    base = make_candles(300, seed=14)
    provider = StaticCandleProvider()
    provider.add("EURUSD", "H1", base[1:])
    provider.add("GBPUSD", "H1", mirrored(base))

    analyzer = CrossMarketAnalyzer(provider, recent_bars=60, historical_bars=250)
    legs = [ExposureLeg("EURUSD", Direction.BUY), ExposureLeg("GBPUSD", Direction.BUY)]
    assessment, report = await analyzer.exposure(
        legs, end=base[-1].time, max_currency_exposure=1.0, max_correlated_exposure=1.0
    )
    assert assessment.exposure_for("USD") == pytest.approx(-2.0)
    assert assessment.overexposed is True
    assert assessment.clusters
    assert report.symbols == ["EURUSD", "GBPUSD"]


# ---------------------------------------------------------------------------
# Persistance et route HTTP
# ---------------------------------------------------------------------------

async def test_persistance_du_cross_market(session: AsyncSession) -> None:
    saved = await pattern_repo.save_cross_market(
        session, "EURUSD", {"GBPUSD": 0.87}, window_days=5, note="H1"
    )
    assert saved.id is not None
    rows = await pattern_repo.latest_cross_market(session)
    assert [row.base_symbol for row in rows] == ["EURUSD"]
    assert rows[0].correlations["GBPUSD"] == pytest.approx(0.87)


async def test_route_cross_market_exige_un_jeton(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/cross-market")
    assert response.status_code == 401


async def test_route_cross_market_sans_donnee(auth_client: AsyncClient) -> None:
    response = await auth_client.get(f"{PREFIX}/cross-market")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["correlations"] == []
    assert payload["exposure"]["legs"] == 0
    assert payload["note"]


async def test_route_cross_market_agrege_les_positions_ouvertes(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    await pattern_repo.save_cross_market(session, "EURUSD", {"GBPUSD": 0.91}, note="H1")
    await pattern_repo.save_cross_market(session, "GBPUSD", {"EURUSD": 0.91}, note="H1")
    for ticket, symbol in ((1, "EURUSD"), (2, "GBPUSD")):
        session.add(
            TradeRecord(
                ticket=ticket,
                symbol=symbol,
                direction=Direction.BUY,
                volume=1.0,
                initial_volume=1.0,
                open_price=1.1,
                state=PositionState.OPEN,
                execution_mode=ExecutionMode.PAPER,
            )
        )
    await session.commit()

    response = await auth_client.get(
        f"{PREFIX}/cross-market", params={"maxCurrencyExposure": 1.0}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["exposure"]["legs"] == 2
    assert payload["exposure"]["overexposed"] is True
    assert payload["exposure"]["dominant"]["currency"] == "USD"
    assert payload["exposure"]["clusters"]
    assert {item["symbol"] for item in payload["positions"]} == {"EURUSD", "GBPUSD"}


# ---------------------------------------------------------------------------
# Contexte cross-market injecte dans le moteur historique
# ---------------------------------------------------------------------------

def test_contexte_cross_market_est_causal() -> None:
    """La correlation servant de caracteristique ne lit que le passe."""
    base = make_candles(300, seed=17)
    reference = MarketHistory(symbol="EURUSD", series={"H1": base[1:]})
    autre = MarketHistory(symbol="GBPUSD", series={"H1": mirrored(base)})

    contexte = causal_correlation_feature(reference, autre, bars=60)
    moment = reference.moments("H1")[200]
    assert contexte(moment) == pytest.approx(1.0, abs=1e-6)

    # Debut de serie : pas assez d'observations, donc aucune valeur inventee.
    assert contexte(reference.moments("H1")[3]) is None
