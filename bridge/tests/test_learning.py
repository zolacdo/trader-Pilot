"""Moteur d'apprentissage : memoire des trades et agregats de performance.

Le point le plus important de cette suite : le systeme mesure, il ne reecrit
JAMAIS ses propres regles. Un test verifie explicitement que les parametres de
risque restent intacts apres un enregistrement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import Direction
from app.models.intelligence import (
    ConsensusOutcome,
    DecisionAction,
    DecisionSource,
    MarketRegime,
)
from app.repositories import pattern_repo, settings_repo
from app.services import learning
from app.services.learning import (
    AUTOMATIC_RULE_UPDATES,
    UNSPECIFIED_STRATEGY,
    TradeLearningRecord,
    collect_records,
    record_trade_outcome,
)
from app.services.learning.performance import overview
from app.services.learning.recorder import BREAKEVEN, LOSS, WIN, aggregate

PREFIX = "/api/v1"
CLOSED = datetime(2024, 3, 5, 16, 30, tzinfo=UTC)


def make_record(
    symbol: str = "EURUSD",
    strategy: str | None = "BREAKOUT",
    source: DecisionSource = DecisionSource.AI_GENERATED,
    r_multiple: float | None = 1.5,
    pnl: float | None = 150.0,
    result: str | None = None,
    closed_at: datetime = CLOSED,
) -> TradeLearningRecord:
    return TradeLearningRecord(
        symbol=symbol,
        direction=Direction.BUY,
        source=source,
        strategy=strategy,
        decision=DecisionAction.BUY,
        entry_price=1.0850,
        stop_loss=1.0800,
        take_profit=1.0950,
        take_profits=[1.0900, 1.0950],
        volume=0.5,
        risk_amount=100.0,
        risk_percent=1.0,
        result=result,
        realized_pnl=pnl,
        r_multiple=r_multiple,
        mfe=1.9,
        mae=-0.4,
        duration_minutes=185.0,
        regime=MarketRegime.TRENDING_UP,
        session_name="LONDON",
        ai_models=["local/qwen", "openrouter/claude"],
        ai_consensus=ConsensusOutcome.CONSENSUS,
        scores={"technical": 0.8, "historical": 0.61, "news": None},
        context={"spreadPoints": 9},
        trade_id=42,
        decision_id=7,
        opened_at=closed_at - timedelta(hours=3),
        closed_at=closed_at,
    )


# ---------------------------------------------------------------------------
# Enregistrement
# ---------------------------------------------------------------------------

def test_le_systeme_ne_reecrit_pas_ses_regles() -> None:
    assert AUTOMATIC_RULE_UPDATES is False
    assert learning.AUTOMATIC_RULE_UPDATES is False


def test_contexte_complet_serialise() -> None:
    payload = make_record().to_dict()
    attendu = {
        "symbol",
        "direction",
        "source",
        "strategy",
        "decision",
        "entryPrice",
        "stopLoss",
        "takeProfit",
        "volume",
        "riskAmount",
        "riskPercent",
        "result",
        "realizedPnl",
        "rMultiple",
        "mfe",
        "mae",
        "durationMinutes",
        "regime",
        "session",
        "aiModels",
        "aiConsensus",
        "scores",
        "context",
    }
    assert attendu <= set(payload)
    assert payload["day"] == "2024-03-05"
    assert payload["aiConsensus"] == "CONSENSUS"
    assert payload["aiModels"] == ["local/qwen", "openrouter/claude"]
    # Une donnee absente reste absente : aucune valeur de remplacement.
    assert payload["scores"]["news"] is None


def test_resultat_deduit_du_pnl_sans_etre_invente() -> None:
    assert make_record(pnl=120.0).derived_result() == WIN
    assert make_record(pnl=-80.0).derived_result() == LOSS
    assert make_record(pnl=0.0).derived_result() == BREAKEVEN
    assert make_record(pnl=None).derived_result() is None
    assert make_record(pnl=-80.0, result="win").derived_result() == WIN


def test_strategie_absente_recoit_une_etiquette_explicite() -> None:
    assert make_record(strategy=None).strategy_key == UNSPECIFIED_STRATEGY


def test_agregat_calcule_le_drawdown() -> None:
    rows = [
        {"closedAt": "2024-03-05T10:00:00", "result": WIN, "rMultiple": 2.0, "realizedPnl": 200.0},
        {"closedAt": "2024-03-05T12:00:00", "result": LOSS, "rMultiple": -1.0, "realizedPnl": -300.0},
        {"closedAt": "2024-03-05T14:00:00", "result": WIN, "rMultiple": 1.0, "realizedPnl": 100.0},
    ]
    resultat = aggregate(rows)
    assert resultat["trades"] == 3
    assert resultat["wins"] == 2
    assert resultat["losses"] == 1
    assert resultat["net_r"] == pytest.approx(2.0)
    assert resultat["net_pnl"] == pytest.approx(0.0)
    assert resultat["max_drawdown"] == pytest.approx(300.0)


def test_agregat_vide_ne_ment_pas() -> None:
    resultat = aggregate([])
    assert resultat["trades"] == 0
    assert resultat["net_r"] == 0.0
    assert resultat["max_drawdown"] == 0.0


async def test_enregistrement_ecrit_journal_et_agregat(session: AsyncSession) -> None:
    record = make_record()
    performance = await record_trade_outcome(session, record)

    assert performance.day == "2024-03-05"
    assert performance.strategy == "BREAKOUT"
    assert performance.trades == 1
    assert performance.wins == 1
    assert performance.net_r == pytest.approx(1.5)

    rows = await collect_records(session, day="2024-03-05")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "EURUSD"
    assert rows[0]["aiConsensus"] == "CONSENSUS"


async def test_enregistrements_successifs_cumulent(session: AsyncSession) -> None:
    await record_trade_outcome(session, make_record(r_multiple=2.0, pnl=200.0))
    performance = await record_trade_outcome(
        session, make_record(r_multiple=-1.0, pnl=-300.0)
    )
    assert performance.trades == 2
    assert performance.wins == 1
    assert performance.losses == 1
    assert performance.net_r == pytest.approx(1.0)
    assert performance.max_drawdown == pytest.approx(300.0)


async def test_strategies_et_origines_restent_separees(session: AsyncSession) -> None:
    await record_trade_outcome(session, make_record(strategy="BREAKOUT"))
    await record_trade_outcome(session, make_record(strategy="PULLBACK"))
    await record_trade_outcome(
        session, make_record(strategy="BREAKOUT", source=DecisionSource.TELEGRAM)
    )

    lignes = await pattern_repo.list_strategy_performance(session)
    cles = {(row.strategy, row.source.value) for row in lignes}
    assert cles == {
        ("BREAKOUT", "AI_GENERATED"),
        ("PULLBACK", "AI_GENERATED"),
        ("BREAKOUT", "TELEGRAM"),
    }
    assert all(row.trades == 1 for row in lignes)


async def test_filtrage_des_enregistrements(session: AsyncSession) -> None:
    await record_trade_outcome(session, make_record(strategy="BREAKOUT"))
    await record_trade_outcome(
        session, make_record(strategy="PULLBACK", source=DecisionSource.TELEGRAM)
    )

    telegram = await collect_records(session, source=DecisionSource.TELEGRAM)
    assert [row["strategy"] for row in telegram] == ["PULLBACK"]

    breakout = await collect_records(session, strategy="BREAKOUT")
    assert [row["source"] for row in breakout] == ["AI_GENERATED"]


async def test_apprentissage_ne_touche_pas_aux_reglages_de_risque(
    session: AsyncSession,
) -> None:
    """Garde-fou : aucun parametre n'est modifie par l'apprentissage."""
    avant = (await settings_repo.get_risk_settings(session)).model_dump()
    avant.pop("updated_at", None)

    await record_trade_outcome(session, make_record(pnl=-500.0, r_multiple=-3.0))
    await record_trade_outcome(session, make_record(pnl=-500.0, r_multiple=-3.0))

    apres = (await settings_repo.get_risk_settings(session)).model_dump()
    apres.pop("updated_at", None)
    assert avant == apres


# ---------------------------------------------------------------------------
# Lecture des performances
# ---------------------------------------------------------------------------

async def test_synthese_par_origine_et_strategie(session: AsyncSession) -> None:
    recent = datetime.now(tz=UTC) - timedelta(days=1)
    await record_trade_outcome(
        session, make_record(strategy="BREAKOUT", closed_at=recent, r_multiple=2.0, pnl=200.0)
    )
    await record_trade_outcome(
        session,
        make_record(
            strategy="PULLBACK",
            source=DecisionSource.TELEGRAM,
            closed_at=recent,
            r_multiple=-1.0,
            pnl=-100.0,
        ),
    )

    payload = await overview(session, days=30)
    assert payload["totalTrades"] == 2
    assert payload["note"]
    sources = {item["source"]: item for item in payload["bySource"]}
    assert sources["AI_GENERATED"]["winRate"] == pytest.approx(100.0)
    assert sources["TELEGRAM"]["winRate"] == pytest.approx(0.0)
    strategies = {item["strategy"]: item for item in payload["byStrategy"]}
    assert strategies["BREAKOUT"]["netR"] == pytest.approx(2.0)
    assert strategies["PULLBACK"]["averageR"] == pytest.approx(-1.0)
    regimes = {item["regime"] for item in payload["byRegime"]}
    assert "TRENDING_UP" in regimes


async def test_synthese_vide_reste_honnete(session: AsyncSession) -> None:
    payload = await overview(session, days=30)
    assert payload["totalTrades"] == 0
    assert payload["bySource"] == []
    assert payload["byStrategy"] == []


# ---------------------------------------------------------------------------
# Route HTTP
# ---------------------------------------------------------------------------

async def test_route_learning_exige_un_jeton(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/learning/performance")
    assert response.status_code == 401


async def test_route_learning_rend_les_performances(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    recent = datetime.now(tz=UTC) - timedelta(days=2)
    await record_trade_outcome(
        session, make_record(closed_at=recent, r_multiple=1.2, pnl=120.0)
    )
    await session.commit()

    response = await auth_client.get(f"{PREFIX}/learning/performance", params={"days": 30})
    assert response.status_code == 200
    payload = response.json()
    assert payload["automaticRuleUpdates"] is False
    assert payload["note"]
    assert payload["totalTrades"] == 1
    assert payload["bySource"][0]["source"] == "AI_GENERATED"
    assert payload["byStrategy"][0]["strategy"] == "BREAKOUT"
