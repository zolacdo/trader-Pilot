"""La comptabilite du watcher doit refleter la gestion reellement appliquee.

Mesure du 15/09/2026 : les signaux 22, 7 et 10 avaient touche TP1 -- le 22
aussi TP2, avec 4,42 R d'excursion favorable -- et etaient comptes -1,00 R
plein. La position reelle, elle, avait encaisse 40 % a TP1 puis vu son stop
remonter a l'entree, parce que ``position_manager`` applique deja
``PARTIAL_CLOSE`` 40/30/30 et le break even sur TP1.

Ces reglages sont les defauts du modele (``app/models/core.py``) : aucun
reglage n'est pose ici, la gestion est active d'office.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import Direction
from app.models.intelligence import Timeframe
from app.services.mt5.interface import Candle
from app.watcher import repository
from app.watcher.config import WatcherConfig
from app.watcher.lifecycle import LifecycleTracker
from app.watcher.models import EntryType, WatcherDecision, WatcherSignal, WatcherStatus
from app.watcher.publisher import TelegramPublisher

BASE = datetime(2024, 1, 1, tzinfo=UTC)


class Recorder:
    """Fonction d'envoi injectee : elle garde les textes, elle n'envoie rien."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, text: str) -> int:
        self.messages.append(text)
        return len(self.messages)


class FakeCandleEngine:
    """Moteur de bougies minimal : rend toujours la serie qu'on lui a donnee."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles
        self.service = None

    async def candles(self, symbol: str, timeframe: Timeframe, bars: int) -> list[Candle]:
        return list(self._candles)


def make_signal(**overrides: object) -> WatcherSignal:
    """Achat : entree 100, stop 98, objectifs 102 / 104 / 106, risque 2."""
    values: dict[str, object] = {
        "symbol": "TESTUSD",
        "broker_symbol": "TESTUSD",
        "direction": Direction.BUY,
        "decision": WatcherDecision.BUY,
        "status": WatcherStatus.CONFIRMED,
        "timeframe": "M15",
        "entry_type": EntryType.MARKET,
        "entry": 100.0,
        "stop_loss": 98.0,
        "digits": 2,
        "take_profit_1": 102.0,
        "take_profit_2": 104.0,
        "take_profit_3": 106.0,
        "risk_distance": 2.0,
        "risk_reward_1": 1.0,
        "risk_reward_2": 2.0,
        "risk_reward_3": 3.0,
        "score": 78.0,
        "confidence": 78,
        "created_at": BASE,
        "expires_at": BASE + timedelta(hours=4),
    }
    values.update(overrides)
    return WatcherSignal(**values)  # type: ignore[arg-type]


def candle(high: float, low: float, close: float, minute: int = 1) -> Candle:
    return Candle(
        time=BASE + timedelta(minutes=minute),
        open=100.0,
        high=high,
        low=low,
        close=close,
        tick_volume=10,
    )


async def suivre(session, candles, config, minutes: int = 30, recorder: Recorder | None = None):
    """Un tour de suivi. Le meme ``recorder`` sert aux tours suivants.

    Ses identifiants de message s'incrementent : deux tours qui repartiraient
    de 1 heurteraient la contrainte d'unicite des publications, ce qui n'a rien
    a voir avec ce que ces tests mesurent.
    """
    recorder = recorder or Recorder()
    tracker = LifecycleTracker(TelegramPublisher(sender=recorder))
    report = await tracker.run_once(
        session, FakeCandleEngine(candles), config, now=BASE + timedelta(minutes=minutes)
    )
    return report, recorder


@pytest.fixture
def config() -> WatcherConfig:
    return WatcherConfig()


async def test_tp1_encaisse_la_fraction_prevue(session, config: WatcherConfig) -> None:
    """40 % a TP1 sur un objectif a 1 R : 0,40 R acquis, 60 % encore en jeu."""
    signal = make_signal()
    await repository.add_signal(session, signal)

    await suivre(session, [candle(high=102.5, low=99.5, close=102.0)], config)

    assert signal.status is WatcherStatus.TP1_HIT
    assert signal.booked_r == pytest.approx(0.4)
    assert signal.open_fraction == pytest.approx(0.6)


async def test_stop_apres_tp1_ne_vaut_plus_moins_un(session, config: WatcherConfig) -> None:
    """Le gain encaisse reste acquis, et le stop remonte protege le reste."""
    signal = make_signal()
    await repository.add_signal(session, signal)

    _, recorder = await suivre(session, [candle(high=102.5, low=99.5, close=102.0)], config)
    await suivre(
        session,
        [candle(high=102.0, low=99.0, close=99.5, minute=5)],
        config,
        minutes=40,
        recorder=recorder,
    )

    assert signal.status is WatcherStatus.SL_HIT
    # 0,40 R encaisse + 60 % sortis a 100,05 (entree + 5 points) = +0,415 R.
    assert signal.result_r == pytest.approx(0.415, abs=0.001)


async def test_un_signal_jamais_gere_vaut_toujours_moins_un(
    session, config: WatcherConfig
) -> None:
    """Sans objectif touche, rien ne bouge : le stop initial vaut -1 R."""
    signal = make_signal()
    await repository.add_signal(session, signal)

    await suivre(session, [candle(high=100.5, low=97.0, close=97.5)], config)

    assert signal.status is WatcherStatus.SL_HIT
    assert signal.result_r == pytest.approx(-1.0)
