"""Tests du shadow mode et du coupe-circuit exposes par l'API.

CDC2 sections 84 a 86 : le systeme decide sans envoyer d'ordre, enregistre ce
qu'il aurait fait, et rend des statistiques comparables. Aucune mesure n'est
extrapolee : ce qui n'est pas mesurable reste ``None``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.core import utcnow
from app.models.enums import Direction
from app.models.intelligence import (
    AIConsensusRecord,
    DecisionAction,
    DecisionSource,
    ShadowOutcome,
    ShadowTrade,
)
from app.repositories import decision_repo
from app.services.confidence.engine import ConfidenceResult
from app.services.decision.circuit_breaker import (
    BreakerLimits,
    BreakerReason,
    CircuitBreaker,
    circuit_breaker,
)
from app.services.decision.engine import DecisionOutcome
from app.services.decision.inputs import TradeLevels
from app.services.decision.shadow import (
    ShadowEngine,
    build_report,
    build_shadow_trade,
    close_shadow_trade,
    compute_stats,
    outcome_for,
)

PREFIX = "/api/v1"


def _niveaux() -> TradeLevels:
    return TradeLevels(
        direction=Direction.BUY,
        entry_price=3500.0,
        entry_min=3498.0,
        entry_max=3502.0,
        stop_loss=3480.0,
        take_profits=[3540.0],
        expected_rr=2.0,
        first_target_rr=2.0,
        risk_distance=20.0,
        method="structure+atr",
    )


def _verdict(
    action: DecisionAction = DecisionAction.BUY,
    direction: Direction | None = Direction.BUY,
    source: DecisionSource = DecisionSource.AI_GENERATED,
) -> DecisionOutcome:
    return DecisionOutcome(
        action=action,
        symbol="XAUUSD",
        source=source,
        direction=direction,
        confidence=ConfidenceResult(score=82.0),
        reason="Contexte favorable.",
    )


def _simule(
    r: float | None,
    *,
    outcome: ShadowOutcome = ShadowOutcome.WOULD_BUY,
    source: DecisionSource = DecisionSource.AI_GENERATED,
    decision_id: int | None = None,
) -> ShadowTrade:
    return ShadowTrade(
        decision_id=decision_id,
        symbol="XAUUSD",
        outcome=outcome,
        direction=Direction.BUY if outcome is ShadowOutcome.WOULD_BUY else None,
        r_multiple=r,
        source=source,
    )


# ---------------------------------------------------------------------------
# Traduction d'une decision en trade simule (CDC2 section 84)
# ---------------------------------------------------------------------------

def test_les_actions_se_traduisent_en_would_buy_sell_skip() -> None:
    assert outcome_for(DecisionAction.BUY) is ShadowOutcome.WOULD_BUY
    assert outcome_for(DecisionAction.STRONG_BUY) is ShadowOutcome.WOULD_BUY
    assert outcome_for(DecisionAction.SELL) is ShadowOutcome.WOULD_SELL
    assert outcome_for(DecisionAction.STRONG_SELL) is ShadowOutcome.WOULD_SELL
    assert outcome_for(DecisionAction.WAIT) is ShadowOutcome.WOULD_SKIP
    assert outcome_for(DecisionAction.NO_TRADE) is ShadowOutcome.WOULD_SKIP
    assert outcome_for(DecisionAction.NEEDS_REVIEW) is ShadowOutcome.WOULD_SKIP


def test_un_achat_simule_porte_ses_niveaux() -> None:
    trace = build_shadow_trade(_verdict(), _niveaux(), decision_id=7, volume=0.05)

    assert trace.outcome is ShadowOutcome.WOULD_BUY
    assert trace.entry_price == 3500.0
    assert trace.stop_loss == 3480.0
    assert trace.take_profit == 3540.0
    assert trace.volume == 0.05
    assert trace.decision_id == 7


def test_un_skip_ne_porte_aucun_niveau() -> None:
    trace = build_shadow_trade(
        _verdict(action=DecisionAction.NO_TRADE), _niveaux(), decision_id=8
    )

    assert trace.outcome is ShadowOutcome.WOULD_SKIP
    assert trace.direction is None
    assert trace.entry_price is None
    assert trace.stop_loss is None
    assert trace.take_profit is None


async def test_aucun_ordre_n_est_envoye_en_shadow_mode(paper) -> None:
    """La construction d'une trace ne touche jamais le moteur d'execution."""
    avant = len(await paper.positions())

    build_shadow_trade(_verdict(), _niveaux())
    build_shadow_trade(_verdict(action=DecisionAction.STRONG_SELL), _niveaux())

    assert len(await paper.positions()) == avant == 0


# ---------------------------------------------------------------------------
# Cloture et R
# ---------------------------------------------------------------------------

def test_le_r_d_un_achat_est_calcule_sur_le_risque_reel() -> None:
    trace = close_shadow_trade(build_shadow_trade(_verdict(), _niveaux()), 3540.0)

    assert trace.r_multiple == 2.0
    assert trace.result == "WIN"


def test_le_r_d_une_vente_est_calcule_dans_le_bon_sens() -> None:
    niveaux = TradeLevels(
        direction=Direction.SELL,
        entry_price=3500.0,
        entry_min=3499.0,
        entry_max=3501.0,
        stop_loss=3520.0,
        take_profits=[3460.0],
        risk_distance=20.0,
    )
    verdict = _verdict(action=DecisionAction.SELL, direction=Direction.SELL)

    trace = close_shadow_trade(build_shadow_trade(verdict, niveaux), 3460.0)

    assert trace.r_multiple == 2.0
    assert trace.result == "WIN"


def test_une_perte_donne_un_r_negatif() -> None:
    trace = close_shadow_trade(build_shadow_trade(_verdict(), _niveaux()), 3480.0)

    assert trace.r_multiple == -1.0
    assert trace.result == "LOSS"


def test_sans_niveaux_le_r_reste_inconnu() -> None:
    trace = close_shadow_trade(
        build_shadow_trade(_verdict(action=DecisionAction.NO_TRADE)), 3500.0
    )

    assert trace.r_multiple is None
    assert trace.result == "UNDETERMINED"


# ---------------------------------------------------------------------------
# Statistiques (CDC2 section 85)
# ---------------------------------------------------------------------------

def test_les_statistiques_reprennent_les_mesures_du_cdc() -> None:
    stats = compute_stats(
        [
            _simule(2.0),
            _simule(-1.0),
            _simule(1.5),
            _simule(-1.0),
            _simule(None, outcome=ShadowOutcome.WOULD_SKIP),
        ]
    )

    assert stats.simulated == 4
    assert stats.skipped == 1
    assert stats.closed == 4
    assert stats.wins == 2
    assert stats.losses == 2
    assert stats.win_rate == pytest.approx(0.5)
    assert stats.loss_rate == pytest.approx(0.5)
    assert stats.total_r == pytest.approx(1.5)
    assert stats.average_r == pytest.approx(0.375)
    assert stats.profit_factor == pytest.approx(3.5 / 2.0)


def test_le_drawdown_est_la_plus_forte_baisse_de_la_courbe() -> None:
    stats = compute_stats([_simule(3.0), _simule(-1.0), _simule(-1.5), _simule(2.0)])

    assert stats.max_drawdown_r == pytest.approx(2.5)


def test_sans_perte_le_profit_factor_reste_inconnu() -> None:
    """Aucune division par zero maquillee en infini."""
    stats = compute_stats([_simule(1.0), _simule(2.0)])

    assert stats.profit_factor is None
    assert stats.win_rate == pytest.approx(1.0)


def test_sans_trade_cloture_aucune_statistique_n_est_inventee() -> None:
    stats = compute_stats([_simule(None), _simule(None, outcome=ShadowOutcome.WOULD_SKIP)])

    assert stats.simulated == 1
    assert stats.closed == 0
    assert stats.win_rate is None
    assert stats.average_r is None
    assert stats.max_drawdown_r is None
    assert stats.profit_factor is None


# ---------------------------------------------------------------------------
# Ventilation par source et par moteur
# ---------------------------------------------------------------------------

def test_le_rapport_ventile_par_source_et_par_moteur() -> None:
    traces = [
        _simule(2.0, source=DecisionSource.TELEGRAM),
        _simule(-1.0, source=DecisionSource.TELEGRAM),
        _simule(1.0, source=DecisionSource.AI_GENERATED, decision_id=1),
        _simule(3.0, source=DecisionSource.AI_GENERATED, decision_id=2),
    ]
    moteurs = {1: ShadowEngine.LOCAL_AI, 2: ShadowEngine.ENSEMBLE}

    rapport = build_report(traces, moteurs)

    assert rapport.overall.closed == 4
    assert rapport.by_source[DecisionSource.TELEGRAM].closed == 2
    assert rapport.by_source[DecisionSource.AI_GENERATED].closed == 2
    assert rapport.by_engine[ShadowEngine.TELEGRAM].closed == 2
    assert rapport.by_engine[ShadowEngine.LOCAL_AI].closed == 1
    assert rapport.by_engine[ShadowEngine.ENSEMBLE].closed == 1


def test_une_decision_sans_trace_de_consensus_reste_d_origine_inconnue() -> None:
    rapport = build_report([_simule(1.0, decision_id=99)], {})

    assert ShadowEngine.UNKNOWN in rapport.by_engine


async def test_le_moteur_est_deduit_des_traces_de_consensus(session: AsyncSession) -> None:
    """Deux modeles interroges = confrontation ; un seul = avis unique.

    Les deux avis viennent du meme fournisseur depuis le retrait de l'IA
    locale : c'est leur NOMBRE qui distingue un ensemble d'un avis isole.
    """
    session.add(
        AIConsensusRecord(
            decision_id=1, primary_model="qwen", secondary_model="nemotron"
        )
    )
    session.add(AIConsensusRecord(decision_id=2, primary_model="qwen"))
    # Un enregistrement sans aucun modele ne designe aucun moteur.
    session.add(AIConsensusRecord(decision_id=3))
    await session.flush()

    labels = await decision_repo.engine_labels(session, [1, 2, 3, 4])

    assert labels == {
        1: ShadowEngine.ENSEMBLE,
        2: ShadowEngine.OPENROUTER,
    }


# ---------------------------------------------------------------------------
# Coupe-circuit : mesures et seuils (CDC2 section 86)
# ---------------------------------------------------------------------------


def test_le_coupe_circuit_compte_les_erreurs_dans_sa_fenetre() -> None:
    disjoncteur = CircuitBreaker(BreakerLimits(max_errors=3, error_window_seconds=60))
    base = utcnow()

    disjoncteur.record_error("timeout", now=base)
    disjoncteur.record_error("timeout", now=base + timedelta(seconds=5))
    assert disjoncteur.state.tripped is False

    etat = disjoncteur.record_error("timeout", now=base + timedelta(seconds=10))
    assert etat.tripped is True
    assert etat.reasons[0].reason is BreakerReason.TOO_MANY_ERRORS


def test_les_erreurs_sortent_de_la_fenetre_glissante() -> None:
    disjoncteur = CircuitBreaker(BreakerLimits(max_errors=3, error_window_seconds=60))
    base = utcnow()

    disjoncteur.record_error(now=base)
    disjoncteur.record_error(now=base + timedelta(seconds=10))
    assert disjoncteur.recent_errors(now=base + timedelta(seconds=300)) == 0


def test_les_pertes_consecutives_arment_le_coupe_circuit() -> None:
    disjoncteur = CircuitBreaker(BreakerLimits(max_consecutive_losses=3))

    for _ in range(3):
        disjoncteur.record_trade_result(won=False)

    assert disjoncteur.state.tripped is True
    assert disjoncteur.consecutive_losses == 3


def test_un_gain_remet_la_serie_de_pertes_a_zero() -> None:
    disjoncteur = CircuitBreaker(BreakerLimits(max_consecutive_losses=3))

    disjoncteur.record_trade_result(won=False)
    disjoncteur.record_trade_result(won=False)
    disjoncteur.record_trade_result(won=True)

    assert disjoncteur.consecutive_losses == 0
    assert disjoncteur.state.tripped is False


def test_le_drawdown_maximal_arme_le_coupe_circuit() -> None:
    disjoncteur = CircuitBreaker(BreakerLimits(max_drawdown_percent=8.0))

    assert disjoncteur.report_drawdown(5.0).tripped is False
    assert disjoncteur.report_drawdown(9.5).tripped is True


def test_un_drawdown_inconnu_ne_declenche_rien() -> None:
    disjoncteur = CircuitBreaker()

    assert disjoncteur.report_drawdown(None).tripped is False
    assert disjoncteur.to_dict()["metrics"]["drawdownPercent"] is None


def test_un_spread_anormal_arme_puis_se_leve() -> None:
    disjoncteur = CircuitBreaker(BreakerLimits(max_spread_ratio=3.0))

    assert disjoncteur.report_spread("XAUUSD", 120, 30).tripped is True
    assert disjoncteur.report_spread("XAUUSD", 35, 30).tripped is False


def test_un_spread_sans_reference_ne_declenche_rien() -> None:
    disjoncteur = CircuitBreaker()

    assert disjoncteur.report_spread("XAUUSD", 500, None).tripped is False


def test_le_consensus_ia_obligatoire_indisponible_arme_le_coupe_circuit() -> None:
    disjoncteur = CircuitBreaker()

    assert disjoncteur.report_ai_consensus(available=False, required=True).tripped is True
    assert disjoncteur.report_ai_consensus(available=False, required=False).tripped is False


def test_un_motif_structurel_resiste_a_une_levee_simple() -> None:
    disjoncteur = CircuitBreaker(BreakerLimits(max_consecutive_losses=1))
    disjoncteur.record_trade_result(won=False)

    disjoncteur.clear(BreakerReason.CONSECUTIVE_LOSSES)
    assert disjoncteur.state.tripped is True

    assert disjoncteur.reset(actor="test").tripped is False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

async def test_la_performance_shadow_est_exposee(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    decision = await decision_repo.save_decision(
        session, _verdict().to_record(shadow=True)
    )
    session.add(
        AIConsensusRecord(
            decision_id=decision.id, primary_model="qwen", secondary_model="nemotron"
        )
    )
    gagnant = close_shadow_trade(
        build_shadow_trade(_verdict(), _niveaux(), decision_id=decision.id), 3540.0
    )
    perdant = close_shadow_trade(
        build_shadow_trade(_verdict(), _niveaux(), decision_id=decision.id), 3480.0
    )
    ignore = build_shadow_trade(_verdict(action=DecisionAction.NO_TRADE))
    for trace in (gagnant, perdant, ignore):
        await decision_repo.save_shadow_trade(session, trace)
    await session.commit()

    reponse = await auth_client.get(f"{PREFIX}/shadow/performance")
    assert reponse.status_code == 200
    charge = reponse.json()

    assert charge["overall"]["simulated"] == 2
    assert charge["overall"]["skipped"] == 1
    assert charge["overall"]["winRate"] == pytest.approx(0.5)
    assert charge["overall"]["averageR"] == pytest.approx(0.5)
    assert ShadowEngine.ENSEMBLE.value in charge["byEngine"]
    assert DecisionSource.AI_GENERATED.value in charge["bySource"]
    assert "simul" in charge["disclaimer"].lower()


async def test_la_performance_shadow_exige_un_appairage(client: AsyncClient) -> None:
    reponse = await client.get(f"{PREFIX}/shadow/performance")

    assert reponse.status_code == 401


async def test_l_etat_du_coupe_circuit_est_expose(auth_client: AsyncClient) -> None:
    circuit_breaker.reset(actor="test")
    try:
        reponse = await auth_client.get(f"{PREFIX}/circuit-breaker")
        assert reponse.status_code == 200
        assert reponse.json()["tripped"] is False

        circuit_breaker.report_market_data(False, "Ticks contradictoires sur XAUUSD.")
        charge = (await auth_client.get(f"{PREFIX}/circuit-breaker")).json()

        assert charge["tripped"] is True
        assert charge["allowsAutoTrading"] is False
        assert "incohérent" in charge["summary"].lower() or "Ticks" in charge["summary"]
        assert charge["reasons"][0]["reason"] == "INCONSISTENT_DATA"
        assert charge["limits"]["maxErrors"] >= 1
    finally:
        circuit_breaker.reset(actor="test")


async def test_le_coupe_circuit_exige_un_appairage(client: AsyncClient) -> None:
    reponse = await client.get(f"{PREFIX}/circuit-breaker")

    assert reponse.status_code == 401


async def test_le_shadow_mode_n_execute_aucune_decision(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    """Une decision enregistree en shadow reste non executee."""
    verdict = _verdict()
    ligne = await decision_repo.save_decision(session, verdict.to_record(shadow=True))
    await decision_repo.save_shadow_trade(
        session, build_shadow_trade(verdict, _niveaux(), decision_id=ligne.id)
    )
    await session.commit()

    charge = (await auth_client.get(f"{PREFIX}/decisions?shadow=true")).json()

    assert charge["total"] == 1
    assert charge["items"][0]["shadow"] is True
    assert charge["items"][0]["executed"] is False
    assert charge["items"][0]["tradeId"] is None
