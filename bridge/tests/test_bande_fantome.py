"""Signaux fantomes : mesures en avant, invisibles pour les decisions reelles.

Un fantome est un signal que le systeme aurait publie si le seuil avait ete
plus bas. Il est suivi comme un vrai -- memes bougies, meme comptabilite en R
-- mais il n'est ni publie, ni execute, et il ne doit RIEN peser sur les
decisions reelles.

Le verrou de ce fichier est le premier test : ``portfolio_state`` alimente
l'anti-doublon et le plafond d'exposition. Un fantome qui y compterait
etoufferait un vrai signal, ce qui serait bien pire que de ne rien mesurer.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.enums import Direction
from app.services.market_data.engine import MarketDataEngine
from app.services.mt5.fake_service import FakeMetaTraderService
from app.watcher import repository
from app.watcher.config import WatcherConfig
from app.watcher.engine import WatcherEngine
from app.watcher.models import WatcherStatus
from app.watcher.publisher import TelegramPublisher
from tests.test_gestion_suivie_comme_executee import BASE, Recorder, make_signal

SYMBOL = "XAUUSD"


@pytest.fixture
async def market() -> MarketDataEngine:
    service = FakeMetaTraderService(balance=10000.0)
    await service.initialize()
    return MarketDataEngine(service)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def watcher(recorder: Recorder) -> WatcherEngine:
    return WatcherEngine(TelegramPublisher(sender=recorder))


@pytest.fixture
def config() -> WatcherConfig:
    """Seuil reel hors d'atteinte, plancher fantome atteignable.

    C'est exactement la situation du 16/09/2026 : le marche plafonnait a 66,7
    pour un seuil a 70. Les alertes de surveillance sont coupees pour que le
    seul message possible soit celui d'un signal -- ce qui rend le test
    « aucune publication » concluant.
    """
    settings = WatcherConfig()
    settings.ai_enabled = False
    settings.send_startup_message = False
    settings.send_watch_alerts = False
    settings.minimum_score = 99.0
    settings.minimum_rr = 0.1
    settings.shadow_enabled = True
    settings.shadow_score = 1.0
    return settings


async def test_un_fantome_ne_bloque_pas_un_vrai_signal(session) -> None:
    """Le verrou : sans lui, un fantome a 66 empecherait un vrai signal a 72."""
    fantome = make_signal(
        direction=Direction.SELL, status=WatcherStatus.ACTIVE, score=66.0, shadow=True
    )
    await repository.add_signal(session, fantome)

    etat = await repository.portfolio_state(session, "TESTUSD", Direction.SELL)

    assert etat.active_same_direction is False, "un fantome ne cree pas de doublon"
    assert etat.active_signals == 0
    assert etat.active_same_symbol == 0
    assert etat.signals_today == 0
    assert etat.last_signal_at is None


async def test_un_vrai_signal_bloque_toujours_un_doublon(session) -> None:
    """La garde reste entiere pour les vrais signaux."""
    vrai = make_signal(direction=Direction.SELL, status=WatcherStatus.ACTIVE)
    await repository.add_signal(session, vrai)

    etat = await repository.portfolio_state(session, "TESTUSD", Direction.SELL)

    assert etat.active_same_direction is True
    assert etat.active_signals == 1


async def test_un_fantome_reste_suivi_par_la_boucle(session) -> None:
    """C'est tout l'interet : il doit vivre sa vie pour etre mesurable."""
    fantome = make_signal(status=WatcherStatus.ACTIVE, shadow=True)
    await repository.add_signal(session, fantome)

    ouverts = await repository.open_signals(session)

    assert [item.id for item in ouverts] == [fantome.id]


async def test_un_fantome_n_entre_pas_dans_l_apprentissage(session) -> None:
    """On mesure d'abord ; rien ne contamine les decisions entre-temps."""
    fantome = make_signal(status=WatcherStatus.SL_HIT, result_r=-1.0, shadow=True)
    vrai = make_signal(
        symbol="AUTREUSD",
        broker_symbol="AUTREUSD",
        status=WatcherStatus.SL_HIT,
        result_r=-1.0,
    )
    await repository.add_signal(session, fantome)
    await repository.add_signal(session, vrai)

    denoues = await repository.closed_signals(session)

    assert [item.symbol for item in denoues] == ["AUTREUSD"]


async def test_la_cadence_ignore_les_fantomes(session) -> None:
    """Un fantome ne doit pas faire croire qu'un signal vient de partir."""
    fantome = make_signal(status=WatcherStatus.ACTIVE, shadow=True, created_at=BASE)
    await repository.add_signal(session, fantome)

    assert await repository.last_signal_at(session, "TESTUSD") is None
    assert await repository.count_signals_since(session, BASE - timedelta(days=1)) == 0


async def test_un_fantome_se_denoue_en_silence(session) -> None:
    """Le suivi publie a chaque changement d'etat : un fantome, jamais.

    Sans cette garde, la bande mesuree encombrerait le canal de signaux que
    personne n'a pris, et le lecteur ne pourrait plus distinguer ce qui a
    reellement ete joue.
    """
    from app.services.mt5.interface import Candle
    from app.watcher.lifecycle import LifecycleTracker
    from tests.test_gestion_suivie_comme_executee import FakeCandleEngine

    fantome = make_signal(shadow=True)
    await repository.add_signal(session, fantome)
    recorder = Recorder()
    tracker = LifecycleTracker(TelegramPublisher(sender=recorder))
    bougie = Candle(
        time=BASE + timedelta(minutes=1),
        open=100.0,
        high=100.5,
        low=97.0,
        close=97.5,
        tick_volume=10,
    )

    await tracker.run_once(
        session,
        FakeCandleEngine([bougie]),
        WatcherConfig(),
        now=BASE + timedelta(minutes=30),
    )

    assert fantome.status is WatcherStatus.SL_HIT, "il doit bien etre suivi"
    assert fantome.result_r == pytest.approx(-1.0), "et compte comme un vrai"
    assert recorder.messages == [], "mais sans dire un mot"
    assert await repository.post_mortems(session) == [], "et sans post-mortem"


# ---------------------------------------------------------------------------
# Creation par le moteur
# ---------------------------------------------------------------------------
async def test_un_fantome_nait_quand_seul_le_score_manquait(
    session,
    market: MarketDataEngine,
    watcher: WatcherEngine,
    config: WatcherConfig,
    geometrie_permissive: None,
) -> None:
    outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)

    assert not outcome.decision.is_tradable, "le seuil reel doit rester hors d'atteinte"
    assert outcome.signal is None, "aucun vrai signal ne doit exister"
    assert outcome.shadow_signal is not None
    assert outcome.shadow_signal.shadow is True
    assert outcome.shadow_signal.symbol == SYMBOL


async def test_un_fantome_n_est_ni_publie_ni_execute(
    session,
    market: MarketDataEngine,
    watcher: WatcherEngine,
    config: WatcherConfig,
    recorder: Recorder,
    geometrie_permissive: None,
) -> None:
    """Il mesure, il ne parle pas et il ne touche pas au compte."""
    outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)

    assert outcome.shadow_signal is not None
    assert recorder.messages == []
    assert outcome.published is False
    assert outcome.execution is None
    assert outcome.shadow_signal.published_at is None


async def test_un_seul_fantome_a_la_fois_par_sens(
    session,
    market: MarketDataEngine,
    watcher: WatcherEngine,
    config: WatcherConfig,
    geometrie_permissive: None,
) -> None:
    """Les fantomes ont leur propre anti-doublon, sinon ils inondent la table.

    ``portfolio_state`` exclut les fantomes pour ne pas etouffer les vrais
    signaux -- mais sans garde interne, le moteur en recreerait un a chaque
    tour de 90 secondes sur le meme setup, soit des milliers par jour.
    """
    premier = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
    assert premier.shadow_signal is not None

    second = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)

    assert second.shadow_signal is None
    ouverts = await repository.open_signals(session, SYMBOL)
    assert len([item for item in ouverts if item.shadow]) == 1


async def test_aucun_fantome_si_un_autre_garde_fou_refuse(
    session, market: MarketDataEngine, watcher: WatcherEngine, config: WatcherConfig
) -> None:
    """Un fantome ne vaut que si le score etait le SEUL obstacle.

    Sinon on mesurerait des setups que le gestionnaire de risque aurait
    refuses de toute facon, et la bande paraitrait pire qu'elle n'est.
    """
    config.minimum_rr = 99.0

    outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)

    assert outcome.shadow_signal is None


async def test_le_plancher_fantome_peut_etre_coupe(
    session, market: MarketDataEngine, watcher: WatcherEngine, config: WatcherConfig
) -> None:
    config.shadow_enabled = False

    outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)

    assert outcome.shadow_signal is None
