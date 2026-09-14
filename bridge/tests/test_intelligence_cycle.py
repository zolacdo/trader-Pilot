"""Cycle d'intelligence autonome : assemblage, decision, journalisation.

Aucun acces reseau, aucun terminal MetaTrader : le scan est remplace par des
resultats fabriques a la main, ce qui rend chaque tour reproductible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models.core import utcnow
from app.models.enums import Direction
from app.models.intelligence import (
    MarketRegime,
    NewsEvent,
    NewsImpact,
    TrendState,
)
from app.repositories import ai_repo, decision_repo, settings_repo
from app.services.confidence.engine import ConfidenceEngine
from app.services.decision.inputs import TradeLevels
from app.services.intelligence import assembly, cycle
from app.services.intelligence.scheduler import (
    DEFAULT_SCAN_MINUTES,
    MAX_MINUTES,
    MIN_MINUTES,
    SETTING_SCAN,
    IntelligenceScheduler,
    _read_minutes,
)
from app.services.market_scanner.scanner import ScanResult
from app.services.opportunities.generator import OpportunityDraft
from app.services.strategies.base import StrategyFamily, StrategyProposal


class _FakeEngine:
    """Moteur de marche minimal : seule ``symbol_info`` est sollicitee ici.

    Retourner ``None`` est le cas reel quand le broker ne renseigne pas
    l'instrument ; l'assemblage doit alors retomber sur ses valeurs par defaut
    sans echouer.
    """

    def __init__(self, info=None) -> None:
        self._info = info

    async def symbol_info(self, symbol: str, refresh: bool = False):
        return self._info


def _scan_result(**changes) -> ScanResult:
    """Resultat de scan complet et coherent, base pour chaque test."""
    defaults: dict = {
        "symbol": "XAUUSD",
        "broker_symbol": "XAUUSDm",
        "scanned_at": utcnow(),
        "trend": TrendState.BULLISH,
        "trend_d1": TrendState.BULLISH,
        "trend_h4": TrendState.BULLISH,
        "trend_h1": TrendState.BULLISH,
        "atr": 4.5,
        "atr_ratio": 0.18,
        "support": 2630.0,
        "resistance": 2680.0,
        "price": 2650.0,
        "bid": 2649.8,
        "ask": 2650.2,
        "spread_points": 40,
        "regime": MarketRegime.TRENDING_UP,
        "regime_confidence": 0.8,
        "alignment": 0.9,
        "setup_potential": 0.82,
        "setup_direction": Direction.BUY,
        "reasons": ["Tendance alignée sur trois unités de temps."],
    }
    defaults.update(changes)
    return ScanResult(**defaults)


def _draft(result: ScanResult) -> OpportunityDraft:
    """Opportunite deja formee, pour isoler le cycle du generateur."""
    niveaux = TradeLevels(
        direction=Direction.BUY,
        entry_price=2650.0,
        entry_min=2648.0,
        entry_max=2652.0,
        stop_loss=2640.0,
        take_profits=[2670.0, 2690.0],
        expected_rr=2.0,
        first_target_rr=2.0,
        risk_distance=10.0,
        method="test",
    )
    proposition = StrategyProposal(
        strategy="suivi_de_tendance",
        family=StrategyFamily.TREND_FOLLOWING,
        direction=Direction.BUY,
        score=0.8,
        reasons=["Structure haussière confirmée."],
    )
    confiance = ConfidenceEngine().evaluate([])
    return OpportunityDraft(
        symbol=result.symbol,
        direction=Direction.BUY,
        proposal=proposition,
        levels=niveaux,
        confidence=confiance,
        qualified=True,
        expires_at=utcnow() + timedelta(minutes=30),
    )


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------

def test_structure_de_prix_construite_depuis_le_scan() -> None:
    structure = assembly.price_structure(_scan_result(), None, digits=2, point=0.01)
    assert structure is not None
    assert structure.usable
    assert structure.last_price == 2650.0
    assert 2630.0 in structure.supports
    assert 2680.0 in structure.resistances


def test_sans_volatilite_aucune_structure() -> None:
    """Sans ATR, aucun stop n'est calculable : on refuse plutot que d'inventer."""
    assert assembly.price_structure(_scan_result(atr=None), None) is None
    assert assembly.price_structure(_scan_result(atr=0.0), None) is None
    assert assembly.price_structure(_scan_result(price=None), None) is None


def test_la_vue_technique_reprend_la_note_du_scanner() -> None:
    vue = assembly.technical_view(_scan_result())
    assert vue.score == 0.82
    assert vue.direction is Direction.BUY
    assert vue.aligned_trends(Direction.BUY) == 3
    assert vue.opposed_trends(Direction.BUY) == 0


async def test_actualites_absentes_donnent_un_terrain_degage(session) -> None:
    vue = await assembly.news_view(session, "XAUUSD")
    assert vue.blackout is False
    assert vue.score == 0.75


async def test_une_actualite_a_fort_impact_fait_baisser_la_note(session) -> None:
    session.add(
        NewsEvent(
            raw_hash="h1",
            source="Réserve fédérale",
            title="Décision de taux",
            impact=NewsImpact.HIGH,
            affected_assets=["XAUUSD"],
            received_at=utcnow(),
        )
    )
    await session.flush()

    vue = await assembly.news_view(session, "XAUUSD")
    assert vue.impact is NewsImpact.HIGH
    assert vue.score is not None and vue.score < 0.75


async def test_les_composantes_absentes_restent_absentes(session) -> None:
    """Une lecture manquante ne doit jamais devenir une note neutre inventee."""
    bundle, _ = await assembly.build_bundle(session, _scan_result())
    assert bundle.historical is not None and bundle.historical.score is None
    assert bundle.cross_market is not None and bundle.cross_market.score is None

    confiance = ConfidenceEngine().evaluate(bundle.components(Direction.BUY))
    assert confiance.coverage < 1.0
    assert confiance.missing


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------

async def test_sans_service_de_marche_le_cycle_le_dit(session, monkeypatch) -> None:
    monkeypatch.setattr(cycle, "market_engine", lambda: None)
    rapport = await cycle.run_cycle(session)
    assert rapport.error is not None
    assert rapport.analysed == 0


async def test_aucun_setup_est_un_resultat_normal(session, monkeypatch) -> None:
    """La plupart des tours ne produisent rien, et ce n'est pas une panne."""
    resultat = _scan_result()
    monkeypatch.setattr(cycle, "market_engine", _FakeEngine)
    monkeypatch.setattr(cycle, "run_scan", _fake_scan([resultat]))
    monkeypatch.setattr(cycle.opportunity_generator, "generate", lambda *a, **k: None)

    rapport = await cycle.run_cycle(session)
    assert rapport.scanned == 1
    assert rapport.analysed == 1
    assert rapport.opportunities == 0
    assert rapport.qualified == 0
    assert rapport.outcomes[0].skipped == "aucun setup"


async def test_une_opportunite_produit_une_decision_tracee(session, monkeypatch) -> None:
    resultat = _scan_result()
    monkeypatch.setattr(cycle, "market_engine", _FakeEngine)
    monkeypatch.setattr(cycle, "run_scan", _fake_scan([resultat]))
    monkeypatch.setattr(
        cycle.opportunity_generator, "generate", lambda *a, **k: _draft(resultat)
    )

    rapport = await cycle.run_cycle(session)
    assert rapport.opportunities == 1
    issue = rapport.outcomes[0]
    assert issue.decision_id is not None
    assert issue.action is not None

    enregistrement = await decision_repo.get_decision(session, issue.decision_id)
    assert enregistrement is not None
    assert enregistrement.symbol == "XAUUSD"
    assert enregistrement.reason  # une decision sans motif serait inutilisable
    facteurs = await decision_repo.list_factors(session, issue.decision_id)
    assert facteurs, "la décomposition du score doit être conservée"


async def test_le_mode_observation_simule_sans_ordre(session, monkeypatch) -> None:
    """Tant que l'IA n'est pas autorisee a trader, tout reste en simulation."""
    resultat = _scan_result()
    monkeypatch.setattr(cycle, "market_engine", _FakeEngine)
    monkeypatch.setattr(cycle, "run_scan", _fake_scan([resultat]))
    monkeypatch.setattr(
        cycle.opportunity_generator, "generate", lambda *a, **k: _draft(resultat)
    )

    reglages = await ai_repo.get_settings(session)
    assert reglages.shadow_mode is True

    rapport = await cycle.run_cycle(session)
    assert rapport.shadow_trades == 1

    simulations = await decision_repo.list_shadow_trades(session)
    assert len(simulations) == 1
    assert simulations[0].symbol == "XAUUSD"

    enregistrement = await decision_repo.get_decision(session, rapport.outcomes[0].decision_id)
    assert enregistrement is not None and enregistrement.shadow is True


async def test_un_instrument_en_erreur_n_arrete_pas_le_tour(session, monkeypatch) -> None:
    bon = _scan_result(symbol="EURUSD")
    casse = _scan_result(symbol="GBPUSD", error="cotation indisponible", price=None)
    monkeypatch.setattr(cycle, "market_engine", _FakeEngine)
    monkeypatch.setattr(cycle, "run_scan", _fake_scan([casse, bon]))
    monkeypatch.setattr(cycle.opportunity_generator, "generate", lambda *a, **k: None)

    rapport = await cycle.run_cycle(session)
    assert rapport.scanned == 2
    assert rapport.analysed == 1  # seul l'instrument exploitable est analyse
    assert rapport.outcomes[0].skipped == "cotation indisponible"


def _fake_scan(results):
    async def _scan(session, **kwargs):
        return results

    return _scan


# ---------------------------------------------------------------------------
# Ordonnanceur
# ---------------------------------------------------------------------------

async def test_periode_par_defaut_quand_rien_n_est_configure(session) -> None:
    assert await _read_minutes(SETTING_SCAN, DEFAULT_SCAN_MINUTES) == DEFAULT_SCAN_MINUTES


@pytest.mark.parametrize(
    ("saisi", "attendu"),
    [("0", MIN_MINUTES), ("999999", MAX_MINUTES), ("12", 12.0), ("n'importe quoi", DEFAULT_SCAN_MINUTES)],
)
async def test_periode_ramenee_dans_ses_bornes(session, saisi: str, attendu: float) -> None:
    """Une periode nulle ferait tourner la boucle en continu : on la borne."""
    await settings_repo.set_setting(session, SETTING_SCAN, saisi)
    await session.commit()
    assert await _read_minutes(SETTING_SCAN, DEFAULT_SCAN_MINUTES) == attendu


async def test_l_ordonnanceur_demarre_et_s_arrete_proprement(session) -> None:
    ordonnanceur = IntelligenceScheduler()
    assert ordonnanceur.started is False
    ordonnanceur.start()
    assert ordonnanceur.started is True
    ordonnanceur.start()  # deux appels ne doivent pas doubler les boucles
    # scan, actualites, calendrier, entretien de la boite de reception
    assert len(ordonnanceur._tasks) == 4
    await ordonnanceur.stop()
    assert ordonnanceur.started is False


async def test_une_boucle_survit_a_une_erreur(session) -> None:
    """Une panne d'un tour ne doit pas tuer la boucle : elle est comptee."""
    ordonnanceur = IntelligenceScheduler()

    async def echoue() -> None:
        raise RuntimeError("source injoignable")

    await ordonnanceur._run_guarded(ordonnanceur.state.news, echoue)
    assert ordonnanceur.state.news.failures == 1
    assert ordonnanceur.state.news.last_error is not None
    assert ordonnanceur.state.news.running is False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

async def test_les_routes_exigent_un_appareil_appaire(client: AsyncClient) -> None:
    for methode, chemin in (
        ("GET", "/api/v1/intelligence/status"),
        ("PUT", "/api/v1/intelligence/intervals"),
        ("POST", "/api/v1/intelligence/run/scan"),
    ):
        reponse = await client.request(methode, chemin, json={})
        assert reponse.status_code == 401, f"{methode} {chemin}"


async def test_etat_de_l_intelligence(auth_client: AsyncClient) -> None:
    reponse = await auth_client.get("/api/v1/intelligence/status")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert {"scan", "news", "calendar"} <= set(corps)
    assert corps["intervals"]["scanMinutes"] == DEFAULT_SCAN_MINUTES


async def test_reglage_des_periodes(auth_client: AsyncClient) -> None:
    reponse = await auth_client.put(
        "/api/v1/intelligence/intervals", json={"scanMinutes": 15, "enabled": False}
    )
    assert reponse.status_code == 200
    assert reponse.json()["scanMinutes"] == 15.0
    assert reponse.json()["enabled"] is False


async def test_periode_hors_bornes_refusee(auth_client: AsyncClient) -> None:
    reponse = await auth_client.put("/api/v1/intelligence/intervals", json={"scanMinutes": 0})
    assert reponse.status_code == 422
    assert "période" in reponse.json()["detail"].lower()


async def test_cible_inconnue_refusee(auth_client: AsyncClient) -> None:
    reponse = await auth_client.post("/api/v1/intelligence/run/inconnue")
    assert reponse.status_code == 404
    assert "scan" in reponse.json()["detail"]


def test_la_date_de_scan_reste_comparable() -> None:
    """Le cycle compare des dates : elles doivent toutes porter un fuseau."""
    resultat = _scan_result(scanned_at=datetime(2026, 9, 11, 6, 0, tzinfo=UTC))
    vue = assembly.quote_view(resultat)
    age = vue.age_seconds(utcnow())
    assert age is not None and age >= 0


# ---------------------------------------------------------------------------
# Rattachement des actualites (regressions constatees en production)
# ---------------------------------------------------------------------------

async def test_une_actualite_critique_sans_actif_ne_bloque_pas_tout(session) -> None:
    """Une dépêche mondiale ne doit pas prétendre concerner chaque instrument.

    Constaté en production : une actualité classée critique sans actif ni
    devise rattachés faisait passer les quatre instruments de la watchlist en
    « actualité d'impact critique en cours », ce qui bloquait tout le système.
    """
    session.add(
        NewsEvent(
            raw_hash="globale",
            source="CNBC",
            title="Événement mondial sans actif identifié",
            impact=NewsImpact.CRITICAL,
            affected_assets=[],
            affected_currencies=[],
            received_at=utcnow(),
        )
    )
    await session.flush()

    vue = await assembly.news_view(session, "BTCUSD")
    assert vue.impact is None
    assert vue.score == 0.75


async def test_une_actualite_est_rattachee_par_la_devise(session) -> None:
    """Une dépêche sur l'EUR concerne EURUSD, pas AUDJPY."""
    session.add(
        NewsEvent(
            raw_hash="eur",
            source="BCE",
            title="Décision de taux de la BCE",
            impact=NewsImpact.HIGH,
            affected_assets=[],
            affected_currencies=["EUR"],
            received_at=utcnow(),
        )
    )
    await session.flush()

    concerne = await assembly.news_view(session, "EURUSD")
    assert concerne.impact is NewsImpact.HIGH

    etranger = await assembly.news_view(session, "AUDJPY")
    assert etranger.impact is None


async def test_le_pic_d_equity_est_oublie_au_changement_de_mode(auth_client) -> None:
    """Le papier (10 000) et le démo (50) n'ont pas la même histoire.

    Constaté sur le téléphone : après un passage du papier au démo MT5, le
    tableau de bord affichait 99,50 % de drawdown, et la limite de perte
    maximale aurait refusé tous les ordres.
    """
    from app.database.session import session_scope

    async with session_scope() as session:
        state = await settings_repo.get_trading_state(session)
        state.peak_equity = 10000.0
        state.day_start_balance = 10000.0
        await settings_repo.save_trading_state(session, state)

    reponse = await auth_client.post(
        "/api/v1/trading/execution-mode", json={"mode": "MT5_DEMO"}
    )
    assert reponse.status_code == 200, reponse.text

    async with session_scope() as session:
        state = await settings_repo.get_trading_state(session)
        assert state.peak_equity is None
        # Le solde de reference du jour vient du meme compte : il doit partir
        # aussi, sinon la perte journaliere se mesurerait contre 10 000.
        assert state.day_start_balance is None


# ---------------------------------------------------------------------------
# Consensus IA (regression constatee sur le telephone)
# ---------------------------------------------------------------------------

async def test_le_cycle_demande_un_consensus_avant_de_decider(session, monkeypatch) -> None:
    """Constate a l'usage : « Consensus IA exige mais aucune analyse produite ».

    Le garde-fou reclamait un avis que le cycle ne demandait jamais. Aucune
    entree ne pouvait donc etre validee, quel que soit le score.
    """
    from app.services.decision.inputs import ConsensusView

    resultat = _scan_result()
    draft = _draft(resultat)
    appels: list[str] = []

    async def faux_consensus(prompt, **kwargs):
        appels.append(prompt)
        return _FauxConsensus()

    monkeypatch.setattr(cycle, "market_engine", _FakeEngine)
    monkeypatch.setattr(cycle, "run_scan", _fake_scan([resultat]))
    monkeypatch.setattr(cycle.opportunity_generator, "generate", lambda *a, **k: draft)
    monkeypatch.setattr(cycle.ai_service, "consensus", faux_consensus)
    monkeypatch.setattr(cycle.ai_service, "requires_manual_review", lambda r: False)

    vues: list[ConsensusView | None] = []
    vraie_decision = cycle.decision_engine.decide

    def espion(contexte):
        vues.append(contexte.analysis.consensus)
        return vraie_decision(contexte)

    monkeypatch.setattr(cycle.decision_engine, "decide", espion)

    await cycle.run_cycle(session)

    assert appels, "le consensus doit etre demande pour une opportunite formee"
    assert vues and vues[0] is not None
    assert vues[0].available is True
    # Les niveaux sont donnes au modele, jamais demandes.
    assert "NE PAS MODIFIER" in appels[0]


async def test_une_panne_du_consensus_n_arrete_pas_le_cycle(session, monkeypatch) -> None:
    """Un moteur d'IA en panne doit faire baisser la couverture, pas planter."""
    resultat = _scan_result()
    draft = _draft(resultat)

    async def consensus_en_panne(prompt, **kwargs):
        raise RuntimeError("quota epuise")

    monkeypatch.setattr(cycle, "market_engine", _FakeEngine)
    monkeypatch.setattr(cycle, "run_scan", _fake_scan([resultat]))
    monkeypatch.setattr(cycle.opportunity_generator, "generate", lambda *a, **k: draft)
    monkeypatch.setattr(cycle.ai_service, "consensus", consensus_en_panne)

    rapport = await cycle.run_cycle(session)

    assert rapport.consensus_failures == 1
    assert rapport.outcomes[0].decision_id is not None  # la decision est prise malgre tout


class _FauxConsensus:
    """Consensus favorable minimal, sans reseau."""

    direction = Direction.BUY
    confidence = 0.8
    detail = "Les deux moteurs vont dans le meme sens."
    blocks_auto_trade = False
