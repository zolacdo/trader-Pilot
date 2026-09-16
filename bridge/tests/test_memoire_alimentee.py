"""Une cloture doit alimenter la memoire d'apprentissage.

Le sous-systeme du CDC2 existait en entier -- ``recorder``, agregats par
strategie, routes d'API -- mais ``record_trade_outcome`` n'etait appele de
NULLE PART. ``strategy_performance`` restait donc vide a jamais, les
statistiques d'apprentissage renvoyaient du vide, et le regleur autonome
mesurait une table sans lignes.

Constate le 16/09/2026 : 0 ligne dans ``strategy_performance`` alors que 33
positions avaient ete closes.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.core import utcnow
from app.models.enums import Direction, ExecutionMode, PositionState
from app.models.trading import TradeRecord
from app.repositories import pattern_repo
from app.services.trading.engine import trading_engine


def _trade(pnl: float, ticket: int = 50001) -> TradeRecord:
    ouverture = utcnow() - timedelta(hours=2)
    return TradeRecord(
        ticket=ticket,
        symbol="XAUUSDm",
        direction=Direction.BUY,
        state=PositionState.CLOSED,
        execution_mode=ExecutionMode.MT5_DEMO,
        open_price=3350.0,
        close_price=3360.0 if pnl > 0 else 3340.0,
        initial_volume=0.01,
        volume=0.0,
        stop_loss=3340.0,
        initial_stop_loss=3340.0,
        take_profit=3370.0,
        realized_pnl=pnl,
        opened_at=ouverture,
        closed_at=utcnow(),
    )


async def test_une_cloture_alimente_la_memoire(session) -> None:
    await trading_engine._apply_closed_trades(session, [_trade(pnl=12.5)])

    lignes = await pattern_repo.list_strategy_performance(session)

    assert len(lignes) == 1
    assert lignes[0].trades == 1
    assert lignes[0].wins == 1
    assert lignes[0].net_pnl == pytest.approx(12.5)


async def test_une_perte_est_comptee_comme_telle(session) -> None:
    await trading_engine._apply_closed_trades(session, [_trade(pnl=-8.0)])

    lignes = await pattern_repo.list_strategy_performance(session)

    assert len(lignes) == 1
    assert lignes[0].losses == 1
    assert lignes[0].net_pnl == pytest.approx(-8.0)


async def test_deux_clotures_du_jour_s_agregent(session) -> None:
    """L'agregat est journalier : deux trades du meme jour font une ligne."""
    await trading_engine._apply_closed_trades(
        session, [_trade(pnl=12.5, ticket=50001), _trade(pnl=-8.0, ticket=50002)]
    )

    lignes = await pattern_repo.list_strategy_performance(session)

    assert len(lignes) == 1
    assert lignes[0].trades == 2
    assert lignes[0].wins == 1
    assert lignes[0].losses == 1


async def test_un_echec_d_enregistrement_ne_bloque_pas_la_cloture(session) -> None:
    """La comptabilite du jour prime : elle ne depend pas de la memoire.

    Sans cette garde, une panne de l'apprentissage empecherait de compter une
    perte dans ``day_realized_pnl``, donc de declencher les garde-fous
    journaliers -- exactement l'inverse de ce qu'on veut.
    """
    from app.repositories import settings_repo
    from app.services.learning import recorder

    async def _casse(*args, **kwargs):
        raise RuntimeError("memoire indisponible")

    original = recorder.record_trade_outcome
    recorder.record_trade_outcome = _casse
    try:
        await trading_engine._apply_closed_trades(session, [_trade(pnl=-8.0)])
    finally:
        recorder.record_trade_outcome = original

    etat = await settings_repo.get_trading_state(session)
    assert etat.day_realized_pnl == pytest.approx(-8.0)
    assert etat.consecutive_losses == 1
