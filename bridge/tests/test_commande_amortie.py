"""Amortissement de la commande automatique.

Deux defauts classiques d'un regulateur qui s'actionne seul, verrouilles ici :

* le **broutage** : une esperance qui oscille autour de zero ferait descendre
  puis remonter le seuil a chaque heure, indefiniment. Une bande morte exige
  un ecart franc avant d'agir ;
* la **preuve qui ne se renouvelle pas** : dix operations rentables
  justifieraient un pas toutes les heures jusqu'a la borne, soit cinq pas sur
  une seule et meme mesure. Chaque pas doit etre paye d'un denouement neuf.
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


async def _fantome(session, result_r: float, index: int) -> None:
    await repository.add_signal(
        session,
        make_signal(
            symbol="AUTREUSD",
            broker_symbol="AUTREUSD",
            direction=Direction.BUY if index % 2 else Direction.SELL,
            entry_type=EntryType.MARKET if index % 2 else EntryType.STOP,
            status=WatcherStatus.TP3_HIT if result_r > 0 else WatcherStatus.SL_HIT,
            result_r=result_r,
            shadow=True,
            created_at=utcnow(),
        ),
    )


async def test_une_esperance_trop_faible_ne_fait_rien_bouger(session) -> None:
    """+0,05 R de moyenne n'est pas une preuve, c'est du bruit centre."""
    for index in range(10):
        await _fantome(session, result_r=0.05, index=index)

    assert await learning.review(session, WatcherConfig()) == []
    config = await load_config(session, refresh=True)
    assert config.minimum_score == pytest.approx(70.0)


async def test_un_ecart_franc_fait_bouger_le_seuil(session) -> None:
    """La bande morte laisse passer une preuve nette."""
    for index in range(10):
        await _fantome(session, result_r=1.5, index=index)

    decisions = await learning.review(session, WatcherConfig())

    assert [d.kind for d in decisions] == ["threshold"]
    config = await load_config(session, refresh=True)
    assert config.minimum_score == pytest.approx(69.0)


async def test_un_second_tour_sans_preuve_neuve_ne_bouge_plus(session) -> None:
    """Le cœur de l'amortissement : un pas, une mesure."""
    for index in range(10):
        await _fantome(session, result_r=1.5, index=index)

    premier = await learning.review(session, WatcherConfig())
    assert [d.kind for d in premier] == ["threshold"]

    # Meme population, tour suivant : rien de neuf a apprendre.
    config = await load_config(session, refresh=True)
    second = await learning.review(session, config)

    assert [d.kind for d in second] == []
    apres = await load_config(session, refresh=True)
    assert apres.minimum_score == pytest.approx(69.0), "le seuil ne descend pas deux fois"


async def test_un_denouement_neuf_autorise_un_nouveau_pas(session) -> None:
    """La commande n'est pas bloquee : elle attend d'etre payee."""
    for index in range(10):
        await _fantome(session, result_r=1.5, index=index)
    await learning.review(session, WatcherConfig())

    await _fantome(session, result_r=1.5, index=99)
    config = await load_config(session, refresh=True)
    decisions = await learning.review(session, config)

    assert [d.kind for d in decisions] == ["threshold"]
    apres = await load_config(session, refresh=True)
    assert apres.minimum_score == pytest.approx(68.0)


async def test_un_pouvoir_discriminant_marginal_ne_deplace_aucun_poids(session) -> None:
    """Meme bande morte pour les poids : 0,02 d'ecart ne prouve rien."""
    from tests.test_poids_autoregles import FIABLE, TROMPEUR, _breakdown

    for index in range(10):
        await repository.add_signal(
            session,
            make_signal(
                symbol=f"GAI{index:02d}USD",
                broker_symbol=f"GAI{index:02d}USD",
                status=WatcherStatus.TP3_HIT,
                result_r=2.0,
                score_breakdown=_breakdown(fiable=0.50, trompeur=0.49),
                created_at=utcnow(),
            ),
        )
    for index in range(10):
        await repository.add_signal(
            session,
            make_signal(
                symbol=f"PER{index:02d}USD",
                broker_symbol=f"PER{index:02d}USD",
                status=WatcherStatus.SL_HIT,
                result_r=-1.0,
                score_breakdown=_breakdown(fiable=0.49, trompeur=0.50),
                created_at=utcnow(),
            ),
        )

    decisions = [
        item for item in await learning.review(session, WatcherConfig()) if item.kind == "weight"
    ]

    assert decisions == []
    assert TROMPEUR and FIABLE  # les noms viennent bien du module partage
