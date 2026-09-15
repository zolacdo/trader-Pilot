"""Chaque perte laisse une trace analysable, une seule fois.

Sans cette trace, rien n'empeche le watcher de reproduire l'erreur qu'il vient
de commettre : ses statistiques savent combien il a perdu, pas sur quoi il
s'etait appuye pour le faire.
"""

from __future__ import annotations

import pytest

from app.watcher import repository
from app.watcher.models import EntryType, WatcherStatus
from tests.test_gestion_suivie_comme_executee import BASE, make_signal


async def test_une_perte_ecrit_un_post_mortem(session) -> None:
    signal = make_signal(
        status=WatcherStatus.SL_HIT,
        result_r=-1.0,
        max_favorable_r=1.34,
        max_adverse_r=1.0,
        score_breakdown={
            "criteria": [
                {"key": "market_structure", "ratio": 0.95},
                {"key": "volume", "ratio": 0.20},
            ]
        },
    )
    await repository.add_signal(session, signal)

    trace = await repository.record_post_mortem(session, signal)

    assert trace is not None
    assert trace.symbol == "TESTUSD"
    assert trace.result_r == pytest.approx(-1.0)
    assert trace.max_favorable_r == pytest.approx(1.34)
    assert "market_structure" in trace.criteria_high
    assert "volume" in trace.criteria_low
    assert trace.session_hour == BASE.hour


async def test_un_second_passage_ne_duplique_rien(session) -> None:
    signal = make_signal(status=WatcherStatus.SL_HIT, result_r=-1.0)
    await repository.add_signal(session, signal)

    premier = await repository.record_post_mortem(session, signal)
    second = await repository.record_post_mortem(session, signal)

    assert premier is not None
    assert second is None
    assert len(await repository.post_mortems(session)) == 1


async def test_un_gain_ne_laisse_aucun_post_mortem(session) -> None:
    signal = make_signal(status=WatcherStatus.TP3_HIT, result_r=3.0)
    await repository.add_signal(session, signal)

    assert await repository.record_post_mortem(session, signal) is None


async def test_la_lecon_distingue_un_gain_rendu_d_un_trade_mort(session) -> None:
    """Deux pertes n'apprennent pas la meme chose."""
    rendu = make_signal(status=WatcherStatus.SL_HIT, result_r=-1.0, max_favorable_r=2.10)
    mort = make_signal(
        symbol="AUTREUSD",
        broker_symbol="AUTREUSD",
        status=WatcherStatus.SL_HIT,
        result_r=-1.0,
        max_favorable_r=0.02,
    )
    await repository.add_signal(session, rendu)
    await repository.add_signal(session, mort)

    trace_rendue = await repository.record_post_mortem(session, rendu)
    trace_morte = await repository.record_post_mortem(session, mort)

    assert trace_rendue is not None and trace_morte is not None
    assert "2.10 R" in (trace_rendue.lesson or "")
    assert "jamais travaille" in (trace_morte.lesson or "")


async def test_la_position_reelle_est_rattachee_quand_elle_existe(session) -> None:
    """C'est la position, pas le suivi, qui dit ce que l'argent a fait."""
    from app.models.enums import Direction, ExecutionMode, PositionState
    from app.models.trading import TradeRecord

    signal = make_signal(status=WatcherStatus.SL_HIT, result_r=-1.0)
    await repository.add_signal(session, signal)
    position = TradeRecord(
        ticket=99001,
        symbol="TESTUSD",
        direction=Direction.BUY,
        state=PositionState.CLOSED,
        execution_mode=ExecutionMode.MT5_DEMO,
        realized_pnl=-43.18,
        opened_at=BASE,
    )
    session.add(position)
    await session.flush()

    trouvee = await repository.matching_trade(session, signal)
    trace = await repository.record_post_mortem(session, signal, trouvee)

    assert trace is not None
    assert trace.trade_pnl == pytest.approx(-43.18)


async def test_aucune_position_rattachee_ne_bloque_rien(session) -> None:
    """Le watcher publie aussi sans passer d'ordre : la trace reste ecrite."""
    signal = make_signal(
        entry_type=EntryType.BREAKOUT, status=WatcherStatus.SL_HIT, result_r=-1.0
    )
    await repository.add_signal(session, signal)

    assert await repository.matching_trade(session, signal) is None
    trace = await repository.record_post_mortem(session, signal, None)

    assert trace is not None
    assert trace.trade_id is None
    assert trace.trade_pnl is None
