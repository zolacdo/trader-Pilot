"""Seul un instrument valide par le backtest passe des ordres, et il s'arrete seul.

Mesure du 21/10/2026 : un mois de demo a coute 207 $ a -0,20 R par trade. La
barriere ne laisse trader que ce qui a gagne sur l'historique, et le frein
coupe un instrument des que la demo perd plus que le backtest ne l'annoncait.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.models.enums import Direction, ExecutionMode, PositionState
from app.models.trading import TradeRecord
from app.services.trading.engine import ProcessOutcome
from app.watcher import execution
from app.watcher.config import WatcherConfig

TEXTE = "BUY EURUSD\nEntry 1.1000\nSL 1.0950\nTP1 1.1100"


class Espion:
    def __init__(self) -> None:
        self.appels = 0

    async def handle_message(self, *args: object, **kwargs: object) -> ProcessOutcome:
        self.appels += 1
        return ProcessOutcome(stage="executed", executed=True, signal_id=1)


def _config(**changes: object) -> WatcherConfig:
    reglages: dict[str, object] = {
        "auto_trade": True,
        "validated_symbols": ["EURUSD"],
        "validated_since": (utcnow() - timedelta(days=2)).isoformat(),
        "validation_budget_r": {"EURUSD": 3.0},
    }
    reglages.update(changes)
    return WatcherConfig(**reglages)  # type: ignore[arg-type]


async def _perte(session: AsyncSession, ticket: int, r: float, il_y_a_heures: int = 1) -> None:
    moment = utcnow() - timedelta(hours=il_y_a_heures)
    session.add(
        TradeRecord(
            ticket=ticket,
            symbol="EURUSDm",
            direction=Direction.BUY,
            state=PositionState.CLOSED,
            execution_mode=ExecutionMode.MT5_DEMO,
            r_multiple=r,
            opened_at=moment,
            closed_at=moment,
        )
    )
    await session.flush()


async def _execute(session: AsyncSession, config: WatcherConfig, symbole: str = "EURUSD"):
    return await execution.execute_signal(
        session, TEXTE, config, symbol=symbole, broker_symbol=f"{symbole}m"
    )


async def test_un_instrument_non_valide_ne_trade_pas(session, monkeypatch):
    espion = Espion()
    monkeypatch.setattr(execution, "trading_engine", espion)

    rapport = await _execute(session, _config(), symbole="XAUUSD")

    assert espion.appels == 0
    assert "backtest" in rapport.detail


async def test_aucun_instrument_valide_veut_dire_aucun_ordre(session, monkeypatch):
    espion = Espion()
    monkeypatch.setattr(execution, "trading_engine", espion)

    await _execute(session, WatcherConfig(auto_trade=True))

    assert espion.appels == 0


async def test_un_instrument_valide_trade(session, monkeypatch):
    espion = Espion()
    monkeypatch.setattr(execution, "trading_engine", espion)

    rapport = await _execute(session, _config())

    assert espion.appels == 1
    assert rapport.executed


async def test_le_frein_coupe_quand_la_demo_depasse_le_budget(session, monkeypatch):
    espion = Espion()
    monkeypatch.setattr(execution, "trading_engine", espion)
    for ticket in range(3):
        await _perte(session, 100 + ticket, -1.0)

    rapport = await _execute(session, _config())

    assert espion.appels == 0
    assert "Frein" in rapport.detail


async def test_les_pertes_d_avant_la_validation_ne_comptent_pas(session, monkeypatch):
    espion = Espion()
    monkeypatch.setattr(execution, "trading_engine", espion)
    for ticket in range(5):
        await _perte(session, 200 + ticket, -1.0, il_y_a_heures=24 * 10)

    await _execute(session, _config())

    assert espion.appels == 1


async def test_la_barriere_se_desarme_par_reglage(session, monkeypatch):
    espion = Espion()
    monkeypatch.setattr(execution, "trading_engine", espion)

    await _execute(session, WatcherConfig(auto_trade=True, trade_only_validated=False))

    assert espion.appels == 1
