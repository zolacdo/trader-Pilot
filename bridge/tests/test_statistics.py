"""Statistiques calculees sur les trades reellement fermes (CDC section 36).

Rien n'est estime ni extrapole. Lorsqu'une mesure n'a pas de sens, la valeur
retournee est ``None`` et jamais zero : un zero laisserait croire a un
resultat mesure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import Direction, ExecutionMode, PositionState
from app.models.trading import TradeRecord
from app.repositories import channel_repo
from app.services.statistics import service as stats

DAY = datetime(2025, 6, 4, 8, 0, tzinfo=UTC)

# Serie de reference, verifiee a la main :
#   +200, +100, -50, -150, 0
#   gains bruts 300, pertes brutes 200 -> profit factor 1.5
#   2 gains / 2 pertes / 1 nul sur 5 trades -> taux de reussite 40 %
#   equity cumulee : 200, 300, 250, 100, 100 -> drawdown maximal 200
SERIE = (
    ("XAUUSD", 200.0, 2.0, 0),
    ("XAUUSD", 100.0, 1.0, 1),
    ("EURUSD", -50.0, -0.5, 2),
    ("EURUSD", -150.0, -1.5, 3),
    ("US30", 0.0, 0.0, 4),
)


async def seed(
    session: AsyncSession,
    execution_mode: ExecutionMode = ExecutionMode.PAPER,
    channel_id: int | None = None,
) -> None:
    for index, (symbol, pnl, r_multiple, hours) in enumerate(SERIE):
        session.add(
            TradeRecord(
                signal_id=None,
                channel_id=channel_id,
                execution_mode=execution_mode,
                ticket=500000 + index,
                symbol=symbol,
                direction=Direction.BUY,
                state=PositionState.CLOSED,
                open_price=100.0,
                close_price=101.0,
                initial_volume=0.10,
                volume=0.0,
                closed_volume=0.10,
                realized_pnl=pnl,
                profit=pnl,
                r_multiple=r_multiple,
                opened_at=DAY + timedelta(hours=hours),
                closed_at=DAY + timedelta(hours=hours, minutes=30),
            )
        )
    await session.flush()


# ---------------------------------------------------------------------------
# Base vide : aucune mesure inventee
# ---------------------------------------------------------------------------

async def test_statistiques_sur_une_base_vide(session: AsyncSession) -> None:
    resume = await stats.global_statistics(session)

    assert resume["trades"] == 0
    assert resume["pnl"] == 0.0
    assert resume["winRate"] is None
    assert resume["lossRate"] is None
    assert resume["profitFactor"] is None
    assert resume["averageWin"] is None
    assert resume["averageLoss"] is None
    assert resume["averageR"] is None
    assert resume["bestTrade"] is None
    assert resume["worstTrade"] is None
    assert resume["maxDrawdown"] is None
    assert resume["expectancy"] is None


async def test_ventilations_sur_une_base_vide(session: AsyncSession) -> None:
    assert await stats.by_symbol(session) == []
    assert await stats.by_day(session) == []
    assert await stats.by_hour(session) == []
    assert await stats.by_channel(session) == []
    assert await stats.compare_channels(session) == []


async def test_resume_du_jour_sur_une_base_vide(session: AsyncSession) -> None:
    resume = await stats.daily_summary(session)
    assert resume["trades"] == 0
    assert resume["netPnl"] == 0.0
    assert resume["winRate"] is None
    assert resume["drawdown"] is None


# ---------------------------------------------------------------------------
# Serie de reference
# ---------------------------------------------------------------------------

async def test_mesures_globales_verifiees_a_la_main(session: AsyncSession) -> None:
    await seed(session)
    resume = await stats.global_statistics(session, ExecutionMode.PAPER)

    assert resume["trades"] == 5
    assert resume["wins"] == 2
    assert resume["losses"] == 2
    assert resume["breakEven"] == 1
    assert resume["pnl"] == pytest.approx(100.0)
    assert resume["grossProfit"] == pytest.approx(300.0)
    assert resume["grossLoss"] == pytest.approx(200.0)

    # 300 / 200 = 1.5
    assert resume["profitFactor"] == pytest.approx(1.5)
    # 2 gains sur 5 trades
    assert resume["winRate"] == pytest.approx(40.0)
    assert resume["lossRate"] == pytest.approx(40.0)
    # 300 / 2 gains, -200 / 2 pertes
    assert resume["averageWin"] == pytest.approx(150.0)
    assert resume["averageLoss"] == pytest.approx(-100.0)
    # (2.0 + 1.0 - 0.5 - 1.5 + 0.0) / 5
    assert resume["averageR"] == pytest.approx(0.2)
    assert resume["bestTrade"] == pytest.approx(200.0)
    assert resume["worstTrade"] == pytest.approx(-150.0)
    # Sommet a 300, creux a 100
    assert resume["maxDrawdown"] == pytest.approx(200.0)
    # 100 / 5 trades
    assert resume["expectancy"] == pytest.approx(20.0)
    assert resume["consecutiveWins"] == 2
    assert resume["consecutiveLosses"] == 2


async def test_profit_factor_absent_sans_aucune_perte(session: AsyncSession) -> None:
    """Sans perte, le profit factor est infini : on ne publie pas un chiffre."""
    session.add(
        TradeRecord(
            execution_mode=ExecutionMode.PAPER,
            ticket=600001,
            symbol="XAUUSD",
            direction=Direction.BUY,
            state=PositionState.CLOSED,
            realized_pnl=120.0,
            opened_at=DAY,
            closed_at=DAY + timedelta(minutes=10),
        )
    )
    await session.flush()

    resume = await stats.global_statistics(session, ExecutionMode.PAPER)
    assert resume["profitFactor"] is None
    assert resume["winRate"] == pytest.approx(100.0)
    assert resume["maxDrawdown"] == pytest.approx(0.0)


async def test_les_positions_ouvertes_ne_sont_pas_comptees(session: AsyncSession) -> None:
    await seed(session)
    session.add(
        TradeRecord(
            execution_mode=ExecutionMode.PAPER,
            ticket=700001,
            symbol="XAUUSD",
            direction=Direction.BUY,
            state=PositionState.OPEN,
            realized_pnl=0.0,
            profit=999.0,
            opened_at=DAY,
        )
    )
    await session.flush()

    resume = await stats.global_statistics(session, ExecutionMode.PAPER)
    assert resume["trades"] == 5
    assert resume["pnl"] == pytest.approx(100.0)


async def test_le_mode_d_execution_isole_les_resultats(session: AsyncSession) -> None:
    await seed(session, ExecutionMode.PAPER)
    await seed(session, ExecutionMode.MT5_DEMO)

    papier = await stats.global_statistics(session, ExecutionMode.PAPER)
    demo = await stats.global_statistics(session, ExecutionMode.MT5_DEMO)
    tout = await stats.global_statistics(session)

    assert papier["trades"] == 5
    assert demo["trades"] == 5
    assert tout["trades"] == 10


async def test_repartition_par_instrument(session: AsyncSession) -> None:
    await seed(session)
    lignes = await stats.by_symbol(session, ExecutionMode.PAPER)
    par_symbole = {ligne["symbol"]: ligne for ligne in lignes}

    assert par_symbole["XAUUSD"]["pnl"] == pytest.approx(300.0)
    assert par_symbole["XAUUSD"]["winRate"] == pytest.approx(100.0)
    assert par_symbole["EURUSD"]["pnl"] == pytest.approx(-200.0)
    assert par_symbole["US30"]["breakEven"] == 1
    # Classement du meilleur P&L au moins bon
    assert [ligne["pnl"] for ligne in lignes] == sorted(
        [ligne["pnl"] for ligne in lignes], reverse=True
    )


async def test_repartition_par_jour_et_par_heure(session: AsyncSession) -> None:
    await seed(session)
    par_jour = await stats.by_day(session, ExecutionMode.PAPER)
    par_heure = await stats.by_hour(session, ExecutionMode.PAPER)

    assert len(par_jour) == 1
    assert par_jour[0]["day"] == "2025-06-04"
    assert par_jour[0]["trades"] == 5
    assert [ligne["hour"] for ligne in par_heure] == [8, 9, 10, 11, 12]


async def test_repartition_par_canal(session: AsyncSession) -> None:
    channel = await channel_repo.upsert(session, telegram_id=4001, title="Canal stats")
    await seed(session, channel_id=channel.id)
    await seed(session, channel_id=None)

    lignes = await stats.by_channel(session, ExecutionMode.PAPER)
    par_canal = {ligne["channelId"]: ligne for ligne in lignes}
    assert par_canal[channel.id]["trades"] == 5
    assert par_canal[None]["trades"] == 5


async def test_filtre_par_canal(session: AsyncSession) -> None:
    channel = await channel_repo.upsert(session, telegram_id=4002, title="Canal filtre")
    await seed(session, channel_id=channel.id)
    await seed(session, channel_id=None)

    resume = await stats.global_statistics(session, ExecutionMode.PAPER, channel_id=channel.id)
    assert resume["trades"] == 5
    assert resume["channelId"] == channel.id


async def test_comparaison_des_canaux(session: AsyncSession) -> None:
    channel = await channel_repo.upsert(session, telegram_id=4003, title="Canal compare")
    await seed(session, channel_id=channel.id)

    lignes = await stats.compare_channels(session)
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne["channelId"] == channel.id
    assert ligne["title"] == "Canal compare"
    assert ligne["paperTrades"] == 5
    assert ligne["paperPnl"] == pytest.approx(100.0)
    assert ligne["paperWinRate"] == pytest.approx(40.0)
    assert ligne["paperDrawdown"] == pytest.approx(200.0)
    # Aucune analyse enregistree : rien n'est invente.
    assert ligne["parseRate"] is None
    assert ligne["historyAvailable"] is False


async def test_resume_du_jour(session: AsyncSession) -> None:
    await seed(session)
    resume = await stats.daily_summary(session, "2025-06-04")

    assert resume["day"] == "2025-06-04"
    assert resume["trades"] == 5
    assert resume["profit"] == pytest.approx(300.0)
    assert resume["loss"] == pytest.approx(200.0)
    assert resume["netPnl"] == pytest.approx(100.0)
    assert resume["wins"] == 2
    assert resume["losses"] == 2
    assert resume["winRate"] == pytest.approx(40.0)


async def test_resume_d_un_autre_jour_est_vide(session: AsyncSession) -> None:
    await seed(session)
    resume = await stats.daily_summary(session, "2025-06-05")
    assert resume["trades"] == 0
    assert resume["netPnl"] == 0.0


async def test_resume_avec_une_date_invalide_retombe_sur_aujourd_hui(
    session: AsyncSession,
) -> None:
    resume = await stats.daily_summary(session, "pas-une-date")
    assert resume["day"] == datetime.now(UTC).date().isoformat()


async def test_filtre_temporel(session: AsyncSession) -> None:
    await seed(session)
    # Les cloture ont lieu a 08h30, 09h30, 10h30, 11h30 et 12h30 UTC.
    apres = await stats.global_statistics(
        session, ExecutionMode.PAPER, since=DAY + timedelta(hours=3)
    )
    assert apres["trades"] == 2
    assert apres["since"] is not None
