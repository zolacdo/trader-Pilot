"""Les poids du score se reglent seuls, par transfert a somme nulle.

Le critere qui accompagne le plus les pertes cede un point a celui qui
accompagne le plus les gains. Deux poids bougent, la somme reste 100, et
chacun reste dans sa bande : un critere n'est jamais reduit au silence, car
l'eteindre serait un changement de structure, pas un reglage.

Rien ne bouge sans ``MIN_SAMPLE`` gagnants ET ``MIN_SAMPLE`` perdants : il faut
les deux populations pour dire qu'un critere discrimine, et une seule ne dit
rien du tout.
"""

from __future__ import annotations

import pytest

from app.models.core import utcnow
from app.watcher import learning, repository
from app.watcher.config import DEFAULT_WEIGHTS, WatcherConfig, invalidate_cache, load_config
from app.watcher.models import WatcherStatus
from tests.test_gestion_suivie_comme_executee import make_signal

FIABLE = "market_structure"
TROMPEUR = "momentum"


@pytest.fixture(autouse=True)
def _cache_propre():
    invalidate_cache()
    yield
    invalidate_cache()


def _breakdown(fiable: float, trompeur: float) -> dict:
    """Carte de score minimale : deux criteres, ratios imposes."""
    return {
        "criteria": [
            {"key": FIABLE, "ratio": fiable, "weight": DEFAULT_WEIGHTS[FIABLE]},
            {"key": TROMPEUR, "ratio": trompeur, "weight": DEFAULT_WEIGHTS[TROMPEUR]},
        ]
    }


async def _operation(session, gagnante: bool, index: int) -> None:
    """Un gagnant porte le critere fiable haut, un perdant le trompeur haut."""
    await repository.add_signal(
        session,
        make_signal(
            symbol=f"SYM{index:02d}USD",
            broker_symbol=f"SYM{index:02d}USD",
            status=WatcherStatus.TP3_HIT if gagnante else WatcherStatus.SL_HIT,
            result_r=2.0 if gagnante else -1.0,
            score_breakdown=_breakdown(
                fiable=0.9 if gagnante else 0.2,
                trompeur=0.2 if gagnante else 0.9,
            ),
            created_at=utcnow(),
        ),
    )


async def _peupler(session, gagnants: int, perdants: int) -> None:
    for index in range(gagnants):
        await _operation(session, gagnante=True, index=index)
    for index in range(perdants):
        await _operation(session, gagnante=False, index=100 + index)


async def test_un_critere_trompeur_cede_du_poids_a_un_critere_fiable(session) -> None:
    await _peupler(session, gagnants=10, perdants=10)

    decisions = [
        item for item in await learning.review(session, WatcherConfig()) if item.kind == "weight"
    ]

    assert len(decisions) == 1
    assert decisions[0].key == f"{TROMPEUR} -> {FIABLE}"
    config = await load_config(session, refresh=True)
    assert config.weight(TROMPEUR) == pytest.approx(DEFAULT_WEIGHTS[TROMPEUR] - 1.0)
    assert config.weight(FIABLE) == pytest.approx(DEFAULT_WEIGHTS[FIABLE] + 1.0)


async def test_la_somme_des_poids_ne_bouge_pas(session) -> None:
    """Un transfert, pas une inflation : le total reste 100."""
    await _peupler(session, gagnants=10, perdants=10)
    avant = sum(DEFAULT_WEIGHTS.values())

    await learning.review(session, WatcherConfig())

    config = await load_config(session, refresh=True)
    apres = sum(config.weight(key) for key in DEFAULT_WEIGHTS)
    assert apres == pytest.approx(avant)


async def test_aucun_transfert_sans_les_deux_populations(session) -> None:
    """Dix gagnants et aucun perdant ne prouvent la fiabilite de rien."""
    await _peupler(session, gagnants=10, perdants=0)

    decisions = [
        item for item in await learning.review(session, WatcherConfig()) if item.kind == "weight"
    ]

    assert decisions == []


async def test_aucun_transfert_sous_le_minimum_d_echantillon(session) -> None:
    await _peupler(session, gagnants=9, perdants=9)

    decisions = [
        item for item in await learning.review(session, WatcherConfig()) if item.kind == "weight"
    ]

    assert decisions == []


async def test_un_poids_ne_descend_pas_sous_sa_borne(session) -> None:
    """Au plancher, le critere garde sa voix : l'eteindre n'est pas un reglage."""
    await _peupler(session, gagnants=10, perdants=10)
    config = WatcherConfig()
    config.weights = dict(DEFAULT_WEIGHTS)
    config.weights[TROMPEUR] = config.weight_floor

    decisions = [
        item for item in await learning.review(session, config) if item.kind == "weight"
    ]

    assert decisions == []


async def test_aucun_transfert_quand_tous_les_criteres_discriminent(session) -> None:
    """Sans critere trompeur, il n'y a rien a reprendre a personne."""
    for index in range(10):
        await repository.add_signal(
            session,
            make_signal(
                symbol=f"SYM{index:02d}USD",
                broker_symbol=f"SYM{index:02d}USD",
                status=WatcherStatus.TP3_HIT,
                result_r=2.0,
                score_breakdown=_breakdown(fiable=0.9, trompeur=0.8),
                created_at=utcnow(),
            ),
        )
    for index in range(10):
        await repository.add_signal(
            session,
            make_signal(
                symbol=f"SYM{100 + index:02d}USD",
                broker_symbol=f"SYM{100 + index:02d}USD",
                status=WatcherStatus.SL_HIT,
                result_r=-1.0,
                score_breakdown=_breakdown(fiable=0.2, trompeur=0.1),
                created_at=utcnow(),
            ),
        )

    decisions = [
        item for item in await learning.review(session, WatcherConfig()) if item.kind == "weight"
    ]

    assert decisions == []
