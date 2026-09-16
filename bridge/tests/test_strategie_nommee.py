"""La stratégie qui a produit une position doit rester attachée à elle.

Le ``by_strategy`` du CDC2 §49 regroupait tout sous ``NON_SPECIFIEE`` : rien ne
nommait la stratégie sur une position, donc la comparaison par stratégie
n'existait pas.

Le nom est porté par le **signal**, pas par la position : tout ce qui découle
d'une exécution — position, ordre en attente, position née de cet ordre — porte
déjà ``signal_id``, donc une seule colonne suffit là où deux et une logique de
report auraient été nécessaires.

Et c'est maintenant qu'il faut le faire : une étiquette ne se rattrape pas
après coup. Les premières positions autonomes resteraient anonymes pour
toujours.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.models.enums import Direction, ExecutionMode, PositionState
from app.models.trading import Signal, TradeRecord
from app.repositories import pattern_repo, settings_repo, signal_repo
from app.services.decision.inputs import TradeLevels
from app.services.intelligence import execution
from app.services.trading.engine import ProcessOutcome, trading_engine


class MoteurEspion:
    """Rend un signal_id choisi, pour vérifier ce qui est estampillé dessus."""

    def __init__(self, signal_id: int) -> None:
        self.appels: list[dict[str, Any]] = []
        self._signal_id = signal_id

    async def handle_message(self, session: AsyncSession, **kwargs: Any) -> ProcessOutcome:
        self.appels.append(kwargs)
        return ProcessOutcome(stage="executed", executed=True, signal_id=self._signal_id)


def _niveaux() -> TradeLevels:
    return TradeLevels(
        direction=Direction.BUY,
        entry_price=3350.0,
        entry_min=3349.0,
        entry_max=3351.0,
        stop_loss=3340.0,
        take_profits=[3360.0],
    )


async def _signal_existant(session: AsyncSession) -> Signal:
    return await signal_repo.create(
        session,
        Signal(
            idempotency_key=f"test-{utcnow().timestamp()}",
            raw_text="BUY XAUUSD",
            symbol="XAUUSD",
            broker_symbol="XAUUSDm",
            direction=Direction.BUY,
        ),
    )


async def test_une_execution_autonome_nomme_sa_strategie(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    signal = await _signal_existant(session)
    assert signal.id is not None
    monkeypatch.setattr(execution, "trading_engine", MoteurEspion(signal.id))
    await settings_repo.set_setting(session, execution.SETTING_AUTO_TRADE, True)

    await execution.execute_decision(
        session, "XAUUSD", _niveaux(), shadow_mode=False, strategy="BREAKOUT_RETEST"
    )

    relu = await signal_repo.get(session, signal.id)
    assert relu is not None
    assert relu.strategy == "BREAKOUT_RETEST"


async def test_sans_strategie_le_signal_reste_intact(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un signal Telegram n'a pas de stratégie : on n'en invente pas."""
    signal = await _signal_existant(session)
    assert signal.id is not None
    monkeypatch.setattr(execution, "trading_engine", MoteurEspion(signal.id))
    await settings_repo.set_setting(session, execution.SETTING_AUTO_TRADE, True)

    await execution.execute_decision(session, "XAUUSD", _niveaux(), shadow_mode=False)

    relu = await signal_repo.get(session, signal.id)
    assert relu is not None
    assert relu.strategy is None


async def test_le_nom_arrive_dans_la_memoire_d_apprentissage(
    session: AsyncSession,
) -> None:
    """C'est tout l'intérêt : le ``by_strategy`` du CDC cesse d'être vide."""
    signal = await _signal_existant(session)
    signal.strategy = "BREAKOUT_RETEST"
    await signal_repo.save(session, signal)

    trade = TradeRecord(
        ticket=80001,
        symbol="XAUUSDm",
        direction=Direction.BUY,
        state=PositionState.CLOSED,
        execution_mode=ExecutionMode.MT5_DEMO,
        open_price=3350.0,
        close_price=3360.0,
        initial_volume=0.01,
        realized_pnl=9.5,
        signal_id=signal.id,
        opened_at=utcnow() - timedelta(hours=1),
        closed_at=utcnow(),
    )

    await trading_engine._apply_closed_trades(session, [trade])

    lignes = await pattern_repo.list_strategy_performance(session)
    assert [ligne.strategy for ligne in lignes] == ["BREAKOUT_RETEST"]
    assert lignes[0].trades == 1


async def test_une_position_sans_signal_reste_non_specifiee(
    session: AsyncSession,
) -> None:
    """Rien n'est deviné : sans signal rattaché, la stratégie reste inconnue."""
    from app.services.learning.recorder import UNSPECIFIED_STRATEGY

    trade = TradeRecord(
        ticket=80002,
        symbol="XAUUSDm",
        direction=Direction.BUY,
        state=PositionState.CLOSED,
        execution_mode=ExecutionMode.MT5_DEMO,
        realized_pnl=-4.0,
        opened_at=utcnow() - timedelta(hours=1),
        closed_at=utcnow(),
    )

    await trading_engine._apply_closed_trades(session, [trade])

    lignes = await pattern_repo.list_strategy_performance(session)
    assert [ligne.strategy for ligne in lignes] == [UNSPECIFIED_STRATEGY]
