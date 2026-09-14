"""Analyse de canal et simulation historique (CDC sections 13 et 14).

Le rapport ne contient que des mesures observees. La simulation historique est
volontairement pessimiste : une bougie ou le stop loss ET le take profit sont
atteignables donne ``AMBIGUOUS`` et n'est JAMAIS comptee comme un gain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import BacktestOutcome, Direction, OrderType
from app.models.telegram import Channel, ChannelAnalysis
from app.models.trading import BacktestResult
from app.repositories import channel_repo
from app.services.channels import analyzer, backtester
from app.services.mt5.interface import Candle
from app.services.trading.paper import PaperTradingService

T0 = datetime(2025, 6, 2, 8, 0, tzinfo=UTC)

SIGNAL_GOLD = "XAUUSD BUY\nENTRY 3320\nSL 3310\nTP1 3330\nTP2 3340"
SIGNAL_EURUSD = "EURUSD SELL\nENTRY 1.0900\nSL 1.0940\nTP 1.0820"
SIGNAL_SANS_SL = "GBPUSD BUY\nENTRY 1.2650\nTP 1.2750"


def message(index: int, text: str, minutes: int) -> dict[str, Any]:
    return {"messageId": index, "text": text, "date": T0 + timedelta(minutes=minutes)}


# Jeu fabrique : 10 messages dont 4 signaux structures (un doublon), 3 suivis,
# 2 messages de convivialite et 1 message avec intention mais non exploitable.
HISTORIQUE: list[dict[str, Any]] = [
    message(1, SIGNAL_GOLD, 0),
    message(2, SIGNAL_GOLD, 5),  # doublon fonctionnel a moins de 30 minutes
    message(3, SIGNAL_EURUSD, 10),
    message(4, SIGNAL_SANS_SL, 20),
    message(5, "TP1 HIT", 30),
    message(6, "CLOSE GOLD NOW", 40),
    message(7, "MOVE SL TO BE", 50),
    message(8, "GOOD MORNING FAMILY", 60),
    message(9, "Gold is looking very bullish today", 70),
    message(10, "We will look for a BUY setup later today", 80),
]


async def make_channel(session: AsyncSession) -> Channel:
    channel = await channel_repo.upsert(
        session, telegram_id=3001, title="Canal analyse", username="analyse"
    )
    assert channel.id is not None
    return channel


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

async def test_analyse_de_canal_produit_des_taux_coherents(session: AsyncSession) -> None:
    channel = await make_channel(session)

    analysis = await analyzer.analyze_channel(session, channel, HISTORIQUE)

    assert analysis.messages_scanned == 10
    # 4 signaux structures + 1 message affichant une intention non exploitable
    assert analysis.signal_like_messages == 5
    assert analysis.parsed_messages == 4
    assert analysis.follow_up_messages == 3
    assert analysis.close_messages == 1
    assert analysis.modify_messages == 1
    assert analysis.duplicate_signals == 1

    # 4 signaux structures sur 5 messages d'intention
    assert analysis.structure_quality == 80.0
    assert analysis.parseable_rate == 80.0
    # 3 signaux sur 4 portent un stop loss
    assert analysis.with_stop_loss_rate == 75.0
    assert analysis.with_take_profit_rate == 100.0
    # 2 + 2 + 1 + 1 objectifs pour 4 signaux
    assert analysis.average_take_profits == 1.5

    assert analysis.symbols == {"XAUUSD": 2, "EURUSD": 1, "GBPUSD": 1}
    assert analysis.directions == {"BUY": 3, "SELL": 1}
    assert analysis.first_message_at == T0
    assert analysis.last_message_at == T0 + timedelta(minutes=80)


async def test_les_taux_restent_dans_zero_cent(session: AsyncSession) -> None:
    channel = await make_channel(session)
    analysis = await analyzer.analyze_channel(session, channel, HISTORIQUE)
    for value in (
        analysis.structure_quality,
        analysis.parseable_rate,
        analysis.with_stop_loss_rate,
        analysis.with_take_profit_rate,
    ):
        assert 0.0 <= value <= 100.0


async def test_les_notes_sont_descriptives_et_sans_promesse(session: AsyncSession) -> None:
    channel = await make_channel(session)
    analysis = await analyzer.analyze_channel(session, channel, HISTORIQUE)
    assert analysis.notes is not None
    notes = analysis.notes.lower()
    assert "10 messages analyses" in notes
    assert "sans projection de performance" in notes
    for promesse in ("garanti", "rentable", "meilleur canal", "profit assure"):
        assert promesse not in notes


async def test_analyse_d_un_historique_vide(session: AsyncSession) -> None:
    channel = await make_channel(session)
    analysis = await analyzer.analyze_channel(session, channel, [])
    assert analysis.messages_scanned == 0
    assert analysis.parsed_messages == 0
    # Aucune base de calcul : les taux restent a zero, pas de division hasardeuse.
    assert analysis.structure_quality == 0.0
    assert analysis.signals_per_day == 0.0


async def test_analyse_ignore_les_messages_vides(session: AsyncSession) -> None:
    channel = await make_channel(session)
    analysis = await analyzer.analyze_channel(
        session,
        channel,
        [message(1, "", 0), message(2, "   ", 5), message(3, SIGNAL_GOLD, 10)],
    )
    assert analysis.messages_scanned == 3
    assert analysis.parsed_messages == 1


async def test_l_analyse_est_persistee_et_relisible(session: AsyncSession) -> None:
    channel = await make_channel(session)
    await analyzer.analyze_channel(session, channel, HISTORIQUE)
    dernier = await channel_repo.latest_analysis(session, channel.id)
    assert dernier is not None
    assert dernier.messages_scanned == 10


async def test_analyse_avec_backtest_sur_le_simulateur(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await make_channel(session)

    analysis = await analyzer.analyze_channel(
        session, channel, HISTORIQUE, run_backtest=True, market=paper
    )

    assert analysis.backtest is not None
    resume = analysis.backtest
    # 3 signaux complets (date, instrument, direction, entree, SL, TP)
    assert resume["testable"] == 3
    total = (
        resume["wins"] + resume["losses"] + resume["ambiguous"]
        + resume["undetermined"] + resume["open"]
    )
    assert total == resume["testable"]
    assert resume["disclaimer"] == backtester.DISCLAIMER
    assert "indicative" in resume["disclaimer"]


# ---------------------------------------------------------------------------
# Backtester : marche fictif entierement pilote
# ---------------------------------------------------------------------------

@pytest.fixture
async def analysis_id(session: AsyncSession) -> int:
    """Rapport d'analyse reel : les resultats de backtest y sont rattaches."""
    channel = await make_channel(session)
    analysis = await channel_repo.save_analysis(
        session, ChannelAnalysis(channel_id=channel.id, messages_scanned=0)
    )
    assert analysis.id is not None
    return analysis.id


class ScriptedMarket:
    """Faux marche : rend les bougies programmees pour chaque symbole."""

    def __init__(self, series: dict[str, list[Candle]]) -> None:
        self._series = series

    async def candles(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:
        return list(self._series.get(symbol, []))


def candle(open_: float, high: float, low: float, close: float, minutes: int = 0) -> Candle:
    return Candle(
        time=T0 + timedelta(minutes=minutes),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_volume=100,
    )


def historic(symbol: str, minutes: int, **kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "messageId": minutes,
        "date": T0 + timedelta(minutes=minutes),
        "symbol": symbol,
        "direction": Direction.BUY,
        "entry": 3320.0,
        "stopLoss": 3310.0,
        "takeProfits": [3340.0],
        "orderType": OrderType.MARKET,
    }
    base.update(kwargs)
    return base


async def test_sl_et_tp_dans_la_meme_bougie_donne_ambiguous(session: AsyncSession, analysis_id: int) -> None:
    """Regle non negociable : on ne devine jamais l'ordre des touches."""
    market = ScriptedMarket({"XAUUSD": [candle(3320.0, 3345.0, 3305.0, 3330.0)]})

    resume = await backtester.backtest_signals(
        session, analysis_id=analysis_id, channel_id=1, signals=[historic("XAUUSD", 0)], market=market
    )

    assert resume["ambiguous"] == 1
    assert resume["wins"] == 0
    assert resume["losses"] == 0
    # Hypothese prudente assumee : le pire scenario, jamais un gain.
    assert resume["totalR"] == pytest.approx(backtester.AMBIGUOUS_R)

    resultat = (await session.exec(_select_backtests())).first()
    assert resultat is not None
    assert resultat.outcome is BacktestOutcome.AMBIGUOUS
    assert resultat.r_multiple == pytest.approx(-1.0)
    assert "meme bougie" in resultat.detail


def _select_backtests():  # type: ignore[no-untyped-def]
    from sqlmodel import select

    return select(BacktestResult).order_by(BacktestResult.id)


async def test_take_profit_atteint_seul_donne_win(session: AsyncSession, analysis_id: int) -> None:
    market = ScriptedMarket({"XAUUSD": [candle(3320.0, 3345.0, 3315.0, 3342.0)]})
    resume = await backtester.backtest_signals(
        session, analysis_id=analysis_id, channel_id=1, signals=[historic("XAUUSD", 0)], market=market
    )
    assert resume["wins"] == 1
    assert resume["tp1Hits"] == 1
    # (3340 - 3320) / (3320 - 3310) = 2 R
    assert resume["averageR"] == pytest.approx(2.0)


async def test_stop_loss_atteint_seul_donne_loss(session: AsyncSession, analysis_id: int) -> None:
    market = ScriptedMarket({"XAUUSD": [candle(3320.0, 3325.0, 3305.0, 3308.0)]})
    resume = await backtester.backtest_signals(
        session, analysis_id=analysis_id, channel_id=1, signals=[historic("XAUUSD", 0)], market=market
    )
    assert resume["losses"] == 1
    assert resume["slHits"] == 1
    assert resume["averageR"] == pytest.approx(-1.0)


async def test_entree_jamais_atteinte_reste_undetermined(session: AsyncSession, analysis_id: int) -> None:
    market = ScriptedMarket({"XAUUSD": [candle(3320.0, 3325.0, 3315.0, 3322.0)]})
    signal = historic("XAUUSD", 0, entry=3200.0, stopLoss=3180.0, takeProfits=[3260.0],
                      orderType=OrderType.BUY_LIMIT)
    resume = await backtester.backtest_signals(
        session, analysis_id=analysis_id, channel_id=1, signals=[signal], market=market
    )
    assert resume["undetermined"] == 1
    assert resume["averageR"] is None


async def test_position_toujours_ouverte_en_fin_de_fenetre(session: AsyncSession, analysis_id: int) -> None:
    market = ScriptedMarket({"XAUUSD": [candle(3320.0, 3325.0, 3315.0, 3322.0)]})
    resume = await backtester.backtest_signals(
        session, analysis_id=analysis_id, channel_id=1, signals=[historic("XAUUSD", 0)], market=market
    )
    assert resume["open"] == 1
    # Une position toujours ouverte n'entre dans aucune moyenne.
    assert resume["averageR"] is None


async def test_agregat_complet_sur_cinq_signaux(session: AsyncSession, analysis_id: int) -> None:
    market = ScriptedMarket(
        {
            "XAUUSD": [candle(3320.0, 3345.0, 3315.0, 3342.0)],  # WIN  +2 R
            "EURUSD": [candle(1.0900, 1.0905, 1.0850, 1.0860)],  # LOSS -1 R
            "GBPUSD": [candle(1.2650, 1.2760, 1.2590, 1.2700)],  # AMBIGUOUS -1 R
        }
    )
    signals = [
        historic("XAUUSD", 0),
        historic("EURUSD", 10, entry=1.0900, stopLoss=1.0870, takeProfits=[1.0960]),
        historic("GBPUSD", 20, entry=1.2650, stopLoss=1.2600, takeProfits=[1.2750]),
    ]

    resume = await backtester.backtest_signals(
        session, analysis_id=analysis_id, channel_id=1, signals=signals, market=market
    )

    assert resume == {
        "testable": 3,
        "wins": 1,
        "losses": 1,
        "ambiguous": 1,
        "undetermined": 0,
        "open": 0,
        "averageR": pytest.approx(0.0),
        "totalR": pytest.approx(0.0),
        "theoreticalDrawdownR": pytest.approx(2.0),
        "tp1Hits": 1,
        "slHits": 1,
        "disclaimer": backtester.DISCLAIMER,
    }


async def test_les_signaux_incomplets_ne_sont_pas_testes(session: AsyncSession, analysis_id: int) -> None:
    market = ScriptedMarket({"XAUUSD": [candle(3320.0, 3345.0, 3315.0, 3342.0)]})
    signals = [
        historic("XAUUSD", 0, stopLoss=None),  # sans stop loss
        historic("XAUUSD", 10, takeProfits=[]),  # sans objectif
        historic("XAUUSD", 20, direction=None),  # sans direction
        historic("XAUUSD", 30, date=None),  # sans date
        # Stop loss du mauvais cote : le risque serait negatif
        historic("XAUUSD", 40, stopLoss=3350.0),
    ]
    resume = await backtester.backtest_signals(
        session, analysis_id=analysis_id, channel_id=1, signals=signals, market=market
    )
    assert resume["testable"] == 0


async def test_sans_bougie_disponible_l_issue_reste_indeterminee(
    session: AsyncSession, analysis_id: int
) -> None:
    market = ScriptedMarket({})
    resume = await backtester.backtest_signals(
        session, analysis_id=analysis_id, channel_id=1, signals=[historic("XAUUSD", 0)], market=market
    )
    assert resume["undetermined"] == 1
    resultat = (await session.exec(_select_backtests())).first()
    assert resultat is not None
    assert "Aucune bougie" in resultat.detail


async def test_une_vente_est_rejouee_dans_le_bon_sens(session: AsyncSession, analysis_id: int) -> None:
    market = ScriptedMarket({"XAUUSD": [candle(3320.0, 3325.0, 3295.0, 3300.0)]})
    signal = historic(
        "XAUUSD", 0, direction=Direction.SELL, entry=3320.0, stopLoss=3330.0,
        takeProfits=[3300.0],
    )
    resume = await backtester.backtest_signals(
        session, analysis_id=analysis_id, channel_id=1, signals=[signal], market=market
    )
    assert resume["wins"] == 1
    assert resume["averageR"] == pytest.approx(2.0)
