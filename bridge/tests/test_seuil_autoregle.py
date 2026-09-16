"""Le seuil de publication se regle seul, dans les deux sens.

Il baisse quand la bande mesuree sous lui s'avere rentable, il monte quand ce
qui est publie perd de l'argent. Jamais sur moins de ``MIN_SAMPLE`` operations,
jamais hors des bornes declarees, jamais d'un bond : un point par decision.

La bande fantome est le capteur qui autorise la baisse. Sans elle, descendre le
seuil serait un pari sur une bande dont personne n'a mesure la valeur.
"""

from __future__ import annotations

import pytest

from app.models.core import utcnow
from app.models.enums import Direction
from app.watcher import learning, repository
from app.watcher.config import WatcherConfig, invalidate_cache, load_config
from app.watcher.models import EntryType, WatcherStatus
from tests.test_gestion_suivie_comme_executee import make_signal


@pytest.fixture(autouse=True)
def _cache_propre():
    invalidate_cache()
    yield
    invalidate_cache()


async def _denoue(
    session,
    result_r: float,
    shadow: bool,
    index: int = 0,
    symbol: str = "AUTREUSD",
) -> None:
    """Une operation close, reelle ou fantome.

    Les types d'entree alternent et l'instrument n'est pas surveille : ainsi
    aucune regle de bannissement ne se declenche, et ces tests ne mesurent que
    le reglage du seuil.
    """
    signal = make_signal(
        symbol=symbol,
        broker_symbol=symbol,
        direction=Direction.BUY if index % 2 else Direction.SELL,
        entry_type=EntryType.MARKET if index % 2 else EntryType.STOP,
        status=WatcherStatus.TP3_HIT if result_r > 0 else WatcherStatus.SL_HIT,
        result_r=result_r,
        shadow=shadow,
        created_at=utcnow(),
    )
    await repository.add_signal(session, signal)


async def test_le_seuil_baisse_quand_la_bande_fantome_gagne(session) -> None:
    """Dix fantomes rentables : la bande merite d'etre ouverte, d'un point."""
    for index in range(10):
        await _denoue(session, result_r=1.5, shadow=True, index=index)

    decisions = await learning.review(session, WatcherConfig())

    assert [d.kind for d in decisions] == ["threshold"]
    assert decisions[0].sample == 10
    config = await load_config(session, refresh=True)
    assert config.minimum_score == pytest.approx(69.0)


async def test_le_seuil_monte_quand_les_vrais_signaux_perdent(session) -> None:
    for index in range(10):
        await _denoue(session, result_r=-1.0, shadow=False, index=index)

    decisions = await learning.review(session, WatcherConfig())

    assert [d.kind for d in decisions] == ["threshold"]
    config = await load_config(session, refresh=True)
    assert config.minimum_score == pytest.approx(71.0)


async def test_rien_ne_bouge_sous_le_minimum_d_echantillon(session) -> None:
    """Neuf operations ne suffisent pas : on ajusterait du bruit."""
    for index in range(9):
        await _denoue(session, result_r=1.5, shadow=True, index=index)

    assert await learning.review(session, WatcherConfig()) == []
    config = await load_config(session, refresh=True)
    assert config.minimum_score == pytest.approx(70.0)


async def test_le_seuil_ne_franchit_pas_sa_borne_basse(session) -> None:
    """A 65, la bande est entierement ouverte : plus rien a concede."""
    for index in range(10):
        await _denoue(session, result_r=1.5, shadow=True, index=index)
    config = WatcherConfig()
    config.minimum_score = 65.0

    assert await learning.review(session, config) == []


async def test_une_contradiction_ne_fait_rien_bouger(session) -> None:
    """Publie perdant ET bande gagnante : les deux sens s'annulent.

    Monter abandonnerait la bande rentable, baisser ajouterait du volume a des
    signaux qui perdent. Aucune des deux n'est defendable, donc on s'abstient.
    """
    for index in range(10):
        await _denoue(session, result_r=-1.0, shadow=False, index=index)
        await _denoue(session, result_r=1.5, shadow=True, index=index)

    decisions = await learning.review(session, WatcherConfig())

    assert [d.kind for d in decisions] == []
    config = await load_config(session, refresh=True)
    assert config.minimum_score == pytest.approx(70.0)


async def test_une_version_precedente_ne_fait_pas_bouger_le_seuil(session) -> None:
    """Meme garde que pour les bannissements, et pour la meme raison.

    Les operations mesurees « sur position entiere » portent des -1 R pleins
    qui ne correspondaient pas au compte. Les laisser commander le seuil, ce
    serait le relever sur des pertes qui n'en etaient pas.
    """
    for index in range(10):
        signal = make_signal(
            symbol="AUTREUSD",
            broker_symbol="AUTREUSD",
            entry_type=EntryType.MARKET if index % 2 else EntryType.STOP,
            status=WatcherStatus.SL_HIT,
            result_r=-1.0,
            strategy_version="market_watcher_v1.0",
            created_at=utcnow(),
        )
        await repository.add_signal(session, signal)

    assert await learning.review(session, WatcherConfig()) == []
    config = await load_config(session, refresh=True)
    assert config.minimum_score == pytest.approx(70.0)


async def test_sans_borne_declaree_le_seuil_ne_bouge_pas(session) -> None:
    """Regle 2 : une borne absente vaut interdiction, jamais permission."""
    for index in range(10):
        await _denoue(session, result_r=1.5, shadow=True, index=index)
    config = WatcherConfig()
    config.learning_bounds = {}

    assert await learning.review(session, config) == []
