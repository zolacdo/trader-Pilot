"""Moteur de patterns historiques : features, similarite, analogues, walk-forward.

Aucun reseau, aucun MT5 : les bougies sont generees de facon deterministe.
Les tests verifient que le moteur MESURE (et refuse de conclure) plutot qu'il
ne recommande.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import Direction
from app.models.intelligence import MarketRegime
from app.repositories import pattern_repo
from app.services.historical_patterns import (
    HistoricalPatternEngine,
    MarketHistory,
    StaticCandleProvider,
    build_features,
    evaluate_outcome,
    feature_scales,
    load_history,
    run_walk_forward,
    similarity,
    split_history,
)
from app.services.historical_patterns.features import MIN_BARS, session_of
from app.services.historical_patterns.outcomes import NEGATIVE, NEUTRAL, POSITIVE
from app.services.historical_patterns.similarity import SIMILARITY_WARNING
from app.services.mt5.interface import Candle

PREFIX = "/api/v1"
ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fabrique de bougies deterministe, reutilisee par les autres suites
# ---------------------------------------------------------------------------

def make_candles(
    count: int,
    start: datetime = ORIGIN,
    step_hours: int = 1,
    seed: int = 7,
    base: float = 1.1000,
    cycle: int = 40,
) -> list[Candle]:
    """Serie synthetique alternant phases haussieres et baissieres."""
    rng = random.Random(seed)
    candles: list[Candle] = []
    price = base
    moment = start
    for index in range(count):
        drift = 0.00006 * (1 if (index // cycle) % 2 == 0 else -1)
        close = price + rng.gauss(drift, 0.0009)
        high = max(price, close) + abs(rng.gauss(0, 0.0004))
        low = min(price, close) - abs(rng.gauss(0, 0.0004))
        candles.append(
            Candle(time=moment, open=price, high=high, low=low, close=close, tick_volume=100 + index)
        )
        price = close
        moment += timedelta(hours=step_hours)
    return candles


def make_history(
    symbol: str = "EURUSD",
    bars: int = 400,
    seed: int = 7,
    with_higher_timeframes: bool = True,
) -> MarketHistory:
    series = {"H1": make_candles(bars, seed=seed)}
    if with_higher_timeframes:
        series["H4"] = make_candles(max(80, bars // 4), step_hours=4, seed=seed + 1)
        series["D1"] = make_candles(max(70, bars // 24), step_hours=24, seed=seed + 2)
    return MarketHistory(symbol=symbol, series=series)


def rising_history(bars: int = 120, symbol: str = "EURUSD") -> MarketHistory:
    """Serie strictement croissante : resultats previsibles a la main."""
    candles = [
        Candle(
            time=ORIGIN + timedelta(hours=index),
            open=1.0 + index * 0.001,
            high=1.0 + (index + 1) * 0.001 + 0.0005,
            low=1.0 + index * 0.001 - 0.0005,
            close=1.0 + (index + 1) * 0.001,
            tick_volume=100,
        )
        for index in range(bars)
    ]
    return MarketHistory(symbol=symbol, series={"H1": candles})


# ---------------------------------------------------------------------------
# Caracteristiques
# ---------------------------------------------------------------------------

def test_features_absentes_si_historique_trop_court() -> None:
    history = MarketHistory(symbol="EURUSD", series={"H1": make_candles(MIN_BARS - 1)})
    assert build_features(history, ORIGIN + timedelta(hours=MIN_BARS)) is None


def test_features_completes_et_bornees() -> None:
    history = make_history(bars=300)
    moment = history.moments("H1")[-1]
    vector = build_features(history, moment)
    assert vector is not None
    assert vector.numeric["rsi"] is not None
    assert 0.0 <= vector.numeric["rsi"] <= 1.0
    assert -1.0 <= vector.numeric["trend_h1"] <= 1.0
    assert vector.categorical["regime"] in {item.value for item in MarketRegime}
    assert vector.categorical["session"] == session_of(moment)
    assert vector.reference_price is not None


def test_spread_reste_none_sans_donnee() -> None:
    """Une donnee absente n'est jamais remplacee par zero."""
    history = make_history(bars=200)
    vector = build_features(history, history.moments("H1")[-1])
    assert vector is not None
    assert vector.numeric["spread_relative"] is None

    with_spread = build_features(
        history, history.moments("H1")[-1], spread_points=12, point=0.00001
    )
    assert with_spread is not None
    assert with_spread.numeric["spread_relative"] is not None


# ---------------------------------------------------------------------------
# Similarite
# ---------------------------------------------------------------------------

def test_similarite_maximale_avec_soi_meme() -> None:
    history = make_history(bars=300)
    moments = history.moments("H1")
    vectors = [build_features(history, moment) for moment in moments[-60:]]
    clean = [vector for vector in vectors if vector is not None]
    scales = feature_scales(clean)
    score = similarity(clean[-1], clean[-1], scales)
    assert score.value == pytest.approx(1.0)
    assert score.compared > 0


def test_similarite_inferieure_entre_situations_differentes() -> None:
    history = make_history(bars=400)
    moments = history.moments("H1")
    clean = [
        vector
        for vector in (build_features(history, moment) for moment in moments[MIN_BARS:])
        if vector is not None
    ]
    scales = feature_scales(clean)
    scores = [similarity(clean[-1], candidate, scales).value for candidate in clean[:-1]]
    assert scores
    assert min(scores) < 1.0
    assert all(0.0 <= value <= 1.0 for value in scores)


def test_similarite_signale_les_caracteristiques_manquantes() -> None:
    history = make_history(bars=200, with_higher_timeframes=False)
    moments = history.moments("H1")
    clean = [
        vector
        for vector in (build_features(history, moment) for moment in moments[MIN_BARS:])
        if vector is not None
    ]
    score = similarity(clean[-1], clean[-2], feature_scales(clean))
    assert "trend_d1" in score.missing
    assert "trend_h4" in score.missing
    assert "spread_relative" in score.missing


def test_sortie_de_similarite_porte_l_avertissement() -> None:
    history = make_history(bars=200)
    moments = history.moments("H1")
    clean = [
        vector
        for vector in (build_features(history, moment) for moment in moments[MIN_BARS:])
        if vector is not None
    ]
    payload = similarity(clean[-1], clean[-2], feature_scales(clean)).to_dict()
    assert payload["warning"] == SIMILARITY_WARNING
    assert "BUY" not in payload["warning"]


# ---------------------------------------------------------------------------
# Resultats reels
# ---------------------------------------------------------------------------

def test_resultat_mesure_mouvement_mae_et_mfe() -> None:
    history = rising_history(bars=120)
    moment = history.moments("H1")[50]
    outcome = evaluate_outcome(history, moment, hours=4, timeframe="H1")
    assert outcome.complete is True
    assert outcome.move_pct is not None and outcome.move_pct > 0
    assert outcome.mfe_pct is not None and outcome.mfe_pct >= outcome.move_pct
    assert outcome.mae_pct is not None and outcome.mae_pct <= 0


def test_resultat_oriente_par_la_direction() -> None:
    history = rising_history(bars=120)
    moment = history.moments("H1")[50]
    achat = evaluate_outcome(history, moment, hours=4, direction=Direction.BUY)
    vente = evaluate_outcome(history, moment, hours=4, direction=Direction.SELL)
    assert achat.move_pct is not None and vente.move_pct is not None
    assert vente.move_pct == pytest.approx(-achat.move_pct)


def test_resultat_incomplet_reste_none() -> None:
    history = rising_history(bars=60)
    dernier = history.moments("H1")[-1]
    outcome = evaluate_outcome(history, dernier, hours=4)
    assert outcome.complete is False
    assert outcome.move_pct is None
    assert outcome.mae_pct is None


# ---------------------------------------------------------------------------
# Moteur
# ---------------------------------------------------------------------------

def test_analyse_impossible_sur_historique_court() -> None:
    history = MarketHistory(symbol="EURUSD", series={"H1": make_candles(30)})
    engine = HistoricalPatternEngine()
    assert engine.analyse(history, ORIGIN + timedelta(hours=29)) is None


def test_analyse_produit_des_statistiques_coherentes() -> None:
    history = make_history(bars=500)
    engine = HistoricalPatternEngine(min_similarity=0.6)
    as_of = history.moments("H1")[-1]
    analysis = engine.analyse(history, as_of)

    assert analysis is not None
    assert analysis.scanned > 0
    counts = analysis.counts()
    assert sum(counts.values()) == analysis.matches
    if analysis.matches:
        assert analysis.similarity_mean is not None
        assert 0.6 <= analysis.similarity_mean <= 1.0
        assert analysis.analogues[0].score.value >= analysis.analogues[-1].score.value


def test_sortie_api_du_moteur_ne_recommande_rien() -> None:
    history = make_history(bars=400)
    engine = HistoricalPatternEngine(min_similarity=0.6)
    payload = engine.analyse(history, history.moments("H1")[-1]).to_dict()

    assert payload["warning"] == SIMILARITY_WARNING
    assert payload["disclaimer"]
    # Aucune cle de decision : le moteur decrit, il ne conclut pas.
    assert "action" not in payload
    assert "recommendation" not in payload
    assert "signal" not in payload
    for horizon in payload["horizons"]:
        share = horizon["positiveShare"]
        assert share is None or 0.0 <= share <= 100.0


def test_repartition_des_horizons_est_exhaustive() -> None:
    history = make_history(bars=500)
    engine = HistoricalPatternEngine(min_similarity=0.55, horizons=(1.0, 4.0, 24.0))
    analysis = engine.analyse(history, history.moments("H1")[-1])
    summary = analysis.horizon_summary(4.0)
    if summary["samples"]:
        assert summary["positive"] + summary["negative"] + summary["neutral"] == summary["samples"]
        assert summary["averageMfePct"] >= 0
        assert summary["averageMaePct"] <= 0


def test_classification_respecte_la_bande_neutre() -> None:
    from app.services.historical_patterns.outcomes import classify

    assert classify(0.5, 0.2) == POSITIVE
    assert classify(-0.5, 0.2) == NEGATIVE
    assert classify(0.1, 0.2) == NEUTRAL
    # Sans bande mesurable, aucune conclusion n'est forcee.
    assert classify(0.5, None) == "UNKNOWN"
    assert classify(None, 0.2) == "UNKNOWN"


# ---------------------------------------------------------------------------
# Source de donnees injectee
# ---------------------------------------------------------------------------

async def test_chargement_via_source_injectee() -> None:
    provider = StaticCandleProvider()
    provider.add("EURUSD", "H1", make_candles(200))
    provider.add("EURUSD", "H4", make_candles(80, step_hours=4))

    history = await load_history(
        provider, "EURUSD", ("H1", "H4", "D1"), ORIGIN, ORIGIN + timedelta(days=30)
    )
    assert history.has("H1")
    assert history.has("H4")
    # Aucune bougie D1 fournie : la serie est absente, pas inventee.
    assert history.has("D1") is False


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def test_decoupage_walk_forward_est_contigu_et_disjoint() -> None:
    history = make_history(bars=400, with_higher_timeframes=False)
    split = split_history(history, "H1", train_ratio=0.7)
    assert split is not None
    assert split.train_end < split.validation_start
    assert split.train_bars + split.validation_bars == history.count("H1")


def test_decoupage_impossible_sur_historique_minuscule() -> None:
    history = MarketHistory(symbol="EURUSD", series={"H1": make_candles(10)})
    assert split_history(history, "H1") is None


def test_rapport_walk_forward_expose_ses_limites() -> None:
    history = make_history(bars=400, with_higher_timeframes=False)
    engine = HistoricalPatternEngine(min_similarity=0.6)
    report = run_walk_forward(engine, history, step_bars=30, max_points=4)

    assert report is not None
    payload = report.to_dict()
    assert payload["note"]
    assert payload["warning"] == SIMILARITY_WARNING
    assert payload["evaluations"] == len(report.evaluations)
    assert report.hit_rate is None or 0.0 <= report.hit_rate <= 100.0
    for point in report.evaluations:
        assert point.moment >= report.split.validation_start


# ---------------------------------------------------------------------------
# Persistance et route HTTP
# ---------------------------------------------------------------------------

async def test_persistance_de_l_analyse(session: AsyncSession) -> None:
    history = make_history(bars=400)
    engine = HistoricalPatternEngine(min_similarity=0.6)
    analysis = engine.analyse(history, history.moments("H1")[-1])

    saved = await pattern_repo.save_pattern(session, analysis)
    assert saved.id is not None
    assert saved.symbol == "EURUSD"
    assert saved.matches == analysis.matches
    assert saved.disclaimer

    latest = await pattern_repo.latest_pattern(session, "EURUSD")
    assert latest is not None and latest.id == saved.id


async def test_route_patterns_exige_un_jeton(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/patterns/EURUSD")
    assert response.status_code == 401


async def test_route_patterns_sans_analyse_le_dit(auth_client: AsyncClient) -> None:
    response = await auth_client.get(f"{PREFIX}/patterns/EURUSD")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["latest"] is None
    assert payload["message"]
    assert payload["warning"] == SIMILARITY_WARNING


async def test_route_patterns_rend_l_analyse_persistee(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    history = make_history(bars=400)
    engine = HistoricalPatternEngine(min_similarity=0.6)
    analysis = engine.analyse(history, history.moments("H1")[-1])
    await pattern_repo.save_pattern(session, analysis)
    await session.commit()

    response = await auth_client.get(f"{PREFIX}/patterns/eurusd")
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "EURUSD"
    assert payload["available"] is True
    assert payload["latest"]["matches"] == analysis.matches
    assert payload["latest"]["warning"] == SIMILARITY_WARNING
