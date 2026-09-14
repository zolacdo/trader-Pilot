"""Interdiction du look-ahead bias (CDC2 section 108).

Ces tests echouent si quelqu'un reintroduit une fuite de donnee future :

* les caracteristiques d'une fenetre ne doivent dependre d'AUCUNE bougie
  posterieure a cette fenetre ;
* seul le calcul du RESULTAT a le droit de regarder devant lui, et jamais
  au-dela de son horizon ;
* une fenetre candidate doit avoir termine son horizon avant l'instant
  analyse ;
* en walk-forward, aucun analogue ne peut provenir de la periode de
  validation.

Le test ``test_le_resultat_change_si_le_futur_change`` garantit que les tests
d'invariance ci-dessus ne sont pas vides de sens : le futur est bien lu, mais
seulement la ou il est autorise.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services.cross_market.analyzer import causal_correlation_feature
from app.services.historical_patterns import (
    HistoricalPatternEngine,
    MarketHistory,
    build_features,
    evaluate_outcome,
    split_history,
)
from app.services.historical_patterns.interface import LookAheadError
from app.services.mt5.interface import Candle
from tests.test_historical_patterns import ORIGIN, make_candles, make_history

HORIZONS = (1.0, 4.0, 24.0)


def _truncate(history: MarketHistory, moment) -> MarketHistory:
    """Copie de l'historique limitee a l'instant donne."""
    return MarketHistory(
        symbol=history.symbol,
        series={
            timeframe: history.upto(timeframe, moment) for timeframe in history.timeframes()
        },
    )


def _distort_future(history: MarketHistory, moment, factor: float = 3.0) -> MarketHistory:
    """Historique identique jusqu'a moment, radicalement different ensuite."""
    series: dict[str, list[Candle]] = {}
    for timeframe in history.timeframes():
        kept = history.upto(timeframe, moment)
        altered = [
            Candle(
                time=candle.time,
                open=candle.open * factor,
                high=candle.high * factor,
                low=candle.low * factor,
                close=candle.close * factor,
                tick_volume=candle.tick_volume,
            )
            for candle in history.future(timeframe, moment)
        ]
        series[timeframe] = kept + altered
    return MarketHistory(symbol=history.symbol, series=series)


class _HistoireSansFutur(MarketHistory):
    """Historique qui refuse toute lecture du futur.

    Sert de garde-fou structurel : la construction des caracteristiques doit
    pouvoir s'executer entierement sur cette classe.
    """

    def future(self, timeframe, moment, until=None):  # type: ignore[override]
        raise LookAheadError(
            "Lecture du futur interdite pendant la construction des caracteristiques"
        )


# ---------------------------------------------------------------------------
# Lecture bornee
# ---------------------------------------------------------------------------

def test_upto_ne_rend_jamais_une_bougie_posterieure() -> None:
    history = make_history(bars=300)
    moment = history.moments("H1")[150]
    for timeframe in history.timeframes():
        for candle in history.upto(timeframe, moment):
            assert candle.time <= moment


def test_future_ne_rend_que_des_bougies_posterieures() -> None:
    history = make_history(bars=300)
    moment = history.moments("H1")[150]
    fenetre = history.future("H1", moment)
    assert fenetre
    assert all(candle.time > moment for candle in fenetre)


# ---------------------------------------------------------------------------
# Les caracteristiques ne voient pas l'avenir
# ---------------------------------------------------------------------------

def test_les_features_ne_lisent_jamais_le_futur() -> None:
    """Garde-fou structurel : build_features ne doit pas appeler future()."""
    base = make_history(bars=300)
    history = _HistoireSansFutur(symbol=base.symbol, series=dict(base.series))
    moment = history.moments("H1")[200]

    vector = build_features(history, moment)
    assert vector is not None

    # La classe refuse bien le futur : la protection est active.
    with pytest.raises(LookAheadError):
        history.future("H1", moment)


def test_features_identiques_sur_historique_tronque() -> None:
    history = make_history(bars=400)
    moment = history.moments("H1")[250]

    complet = build_features(history, moment)
    tronque = build_features(_truncate(history, moment), moment)

    assert complet is not None and tronque is not None
    assert complet.to_dict() == tronque.to_dict()


def test_features_insensibles_a_une_deformation_du_futur() -> None:
    """Si le futur change du tout au tout, les features ne bougent pas."""
    history = make_history(bars=400)
    moment = history.moments("H1")[250]

    avant = build_features(history, moment)
    apres = build_features(_distort_future(history, moment), moment)

    assert avant is not None and apres is not None
    assert avant.to_dict() == apres.to_dict()


def test_le_resultat_change_si_le_futur_change() -> None:
    """Contre-epreuve : sans elle, les tests d'invariance seraient vides."""
    history = make_history(bars=400)
    moment = history.moments("H1")[250]

    initial = evaluate_outcome(history, moment, hours=4)
    deforme = evaluate_outcome(_distort_future(history, moment), moment, hours=4)

    assert initial.move_pct is not None and deforme.move_pct is not None
    assert initial.move_pct != deforme.move_pct


# ---------------------------------------------------------------------------
# Le resultat ne depasse pas son horizon
# ---------------------------------------------------------------------------

def test_le_resultat_ignore_ce_qui_arrive_apres_l_horizon() -> None:
    candles = make_candles(200)
    moment = candles[100].time
    horizon_fin = moment + timedelta(hours=4)

    # Pic gigantesque place APRES l'horizon : il ne doit rien changer.
    perturbes = [
        candle
        if candle.time <= horizon_fin
        else Candle(
            time=candle.time,
            open=candle.open * 10,
            high=candle.high * 10,
            low=candle.low * 10,
            close=candle.close * 10,
            tick_volume=candle.tick_volume,
        )
        for candle in candles
    ]

    reference = evaluate_outcome(
        MarketHistory(symbol="EURUSD", series={"H1": candles}), moment, hours=4
    )
    perturbe = evaluate_outcome(
        MarketHistory(symbol="EURUSD", series={"H1": perturbes}), moment, hours=4
    )
    assert reference.to_dict() == perturbe.to_dict()


# ---------------------------------------------------------------------------
# Le moteur ne retient que des fenetres entierement passees
# ---------------------------------------------------------------------------

def test_les_candidates_terminent_leur_horizon_avant_l_analyse() -> None:
    history = make_history(bars=500)
    engine = HistoricalPatternEngine(horizons=HORIZONS, min_similarity=0.6)
    as_of = history.moments("H1")[-1]

    limite = as_of - timedelta(hours=max(HORIZONS))
    for moment in engine.candidate_moments(history, as_of):
        assert moment <= limite


def test_analyse_identique_si_le_futur_est_retire() -> None:
    """L'analyse a un instant ne doit dependre d'aucune bougie posterieure."""
    history = make_history(bars=500)
    engine = HistoricalPatternEngine(horizons=HORIZONS, min_similarity=0.6)
    as_of = history.moments("H1")[380]

    complet = engine.analyse(history, as_of)
    tronque = engine.analyse(_truncate(history, as_of), as_of)

    assert complet is not None and tronque is not None
    assert complet.matches == tronque.matches
    assert complet.similarity_mean == tronque.similarity_mean
    assert complet.counts() == tronque.counts()
    assert complet.horizon_summary(4.0) == tronque.horizon_summary(4.0)


def test_analyse_insensible_a_une_deformation_du_futur() -> None:
    history = make_history(bars=500)
    engine = HistoricalPatternEngine(horizons=HORIZONS, min_similarity=0.6)
    as_of = history.moments("H1")[380]

    complet = engine.analyse(history, as_of)
    deforme = engine.analyse(_distort_future(history, as_of), as_of)

    assert complet is not None and deforme is not None
    assert complet.to_dict() == deforme.to_dict()


# ---------------------------------------------------------------------------
# Walk-forward : aucune fuite entre apprentissage et validation
# ---------------------------------------------------------------------------

def test_aucun_analogue_ne_vient_de_la_periode_de_validation() -> None:
    history = make_history(bars=600, with_higher_timeframes=False)
    split = split_history(history, "H1", train_ratio=0.7)
    assert split is not None

    engine = HistoricalPatternEngine(horizons=HORIZONS, min_similarity=0.55)
    points = history.moments("H1", start=split.validation_start)[::40][:4]
    assert points

    limite = split.train_end - timedelta(hours=max(HORIZONS))
    verifies = 0
    for moment in points:
        analysis = engine.analyse(history, moment, candidate_end=split.train_end)
        assert analysis is not None
        for analogue in analysis.analogues:
            assert analogue.moment < split.validation_start
            assert analogue.moment <= limite
            verifies += 1
    assert verifies > 0


def test_les_deux_periodes_ne_se_recouvrent_pas() -> None:
    history = make_history(bars=400, with_higher_timeframes=False)
    split = split_history(history, "H1", train_ratio=0.6)
    assert split is not None

    entrainement = set(history.moments("H1", end=split.train_end))
    validation = set(history.moments("H1", start=split.validation_start))
    assert entrainement & validation == set()
    assert len(entrainement) + len(validation) == history.count("H1")


def test_candidate_end_borne_bien_les_analogues() -> None:
    """Sans borne explicite, seules les fenetres anterieures restent eligibles."""
    history = make_history(bars=500, with_higher_timeframes=False)
    engine = HistoricalPatternEngine(horizons=HORIZONS)
    as_of = history.moments("H1")[-1]

    libres = engine.candidate_moments(history, as_of)
    bornees = engine.candidate_moments(history, as_of, candidate_end=history.moments("H1")[200])
    assert len(bornees) < len(libres)
    assert max(bornees) <= history.moments("H1")[200] - timedelta(hours=max(HORIZONS))


def test_origine_des_series_partagee() -> None:
    """Les fabriques de test restent deterministes d'une suite a l'autre."""
    assert make_candles(3)[0].time == ORIGIN
    assert make_candles(5, seed=7)[4].close == make_candles(5, seed=7)[4].close


def test_le_contexte_cross_market_ignore_le_futur() -> None:
    """La caracteristique inter-instruments ne doit pas voir l'avenir."""
    reference = make_history(bars=300, with_higher_timeframes=False)
    autre = make_history(symbol="GBPUSD", bars=300, seed=21, with_higher_timeframes=False)
    moment = reference.moments("H1")[200]

    intact = causal_correlation_feature(reference, autre, bars=60)(moment)
    deforme = causal_correlation_feature(
        _distort_future(reference, moment), _distort_future(autre, moment), bars=60
    )(moment)
    assert intact == deforme


def test_analyse_avec_contexte_cross_market_reste_causale() -> None:
    reference = make_history(bars=400, with_higher_timeframes=False)
    autre = make_history(symbol="GBPUSD", bars=400, seed=23, with_higher_timeframes=False)
    as_of = reference.moments("H1")[-1]

    engine = HistoricalPatternEngine(horizons=HORIZONS, min_similarity=0.6)
    contexte = causal_correlation_feature(reference, autre, bars=60)

    complet = engine.analyse(reference, as_of, cross_market_at=contexte)
    tronque = engine.analyse(
        _truncate(reference, as_of),
        as_of,
        cross_market_at=causal_correlation_feature(
            _truncate(reference, as_of), _truncate(autre, as_of), bars=60
        ),
    )
    assert complet is not None and tronque is not None
    assert complet.reference.numeric["cross_market"] is not None
    assert complet.to_dict() == tronque.to_dict()
