"""L'apprentissage decide peu, tard, et jamais hors de ses bornes.

Sur 21 operations denouees, tout ajustement fin ajusterait du bruit : la
retenue est une exigence, pas une timidite. Les trois regles verrouillees ici
sont celles du spec -- rien sous ``MIN_SAMPLE``, rien hors des bornes
declarees, rien en silence.
"""

from __future__ import annotations

import pytest

from app.models.core import utcnow
from app.watcher import learning, repository
from app.watcher.config import WatcherConfig, invalidate_cache, load_config
from app.watcher.models import STRATEGY_VERSION, EntryType, WatcherStatus
from tests.test_gestion_suivie_comme_executee import make_signal


def _bannissements(decisions: list) -> list:
    """Seules les mises au ban. Le reglage du seuil se teste ailleurs.

    Ces tests fabriquent des operations perdantes, ce qui fait legitimement
    monter le seuil de publication : sans ce filtre, ils mesureraient deux
    regles a la fois et casseraient des que l'une des deux evolue.
    """
    return [item for item in decisions if item.kind in ("entry_type", "symbol")]


async def _denoue(
    session,
    symbol: str,
    entry_type: EntryType,
    result_r: float = -1.0,
    version: str = STRATEGY_VERSION,
) -> None:
    """Un signal clos, avec son post-mortem quand c'est une perte."""
    signal = make_signal(
        symbol=symbol,
        broker_symbol=symbol,
        entry_type=entry_type,
        status=WatcherStatus.SL_HIT if result_r < 0 else WatcherStatus.TP3_HIT,
        result_r=result_r,
        created_at=utcnow(),
        strategy_version=version,
    )
    await repository.add_signal(session, signal)
    await repository.record_post_mortem(session, signal)


@pytest.fixture(autouse=True)
def _cache_propre():
    """La configuration est memorisee : chaque test repart d'une lecture neuve."""
    invalidate_cache()
    yield
    invalidate_cache()


async def test_sous_le_minimum_rien_n_est_decide(session) -> None:
    """Neuf pertes ne suffisent pas : on ne conclut pas sur du bruit."""
    for _ in range(9):
        await _denoue(session, "BREAKUSD", EntryType.BREAKOUT)

    assert _bannissements(await learning.review(session, WatcherConfig())) == []


async def test_dix_pertes_sans_un_gain_ecartent_le_type_d_entree(session) -> None:
    for _ in range(10):
        await _denoue(session, "BREAKUSD", EntryType.BREAKOUT)

    decisions = _bannissements(await learning.review(session, WatcherConfig()))

    assert [decision.key for decision in decisions] == ["BREAKOUT"]
    assert decisions[0].kind == "entry_type"
    assert decisions[0].sample == 10
    config = await load_config(session, refresh=True)
    assert "BREAKOUT" in config.disabled_entry_types


async def test_un_instrument_surveille_sort_de_la_liste(session) -> None:
    """Les types d'entree alternent : seul l'instrument atteint le minimum."""
    for index in range(10):
        entree = EntryType.MARKET if index % 2 else EntryType.STOP
        await _denoue(session, "BTCUSD", entree)

    decisions = _bannissements(await learning.review(session, WatcherConfig()))

    assert [decision.key for decision in decisions] == ["BTCUSD"]
    assert decisions[0].kind == "symbol"
    config = await load_config(session, refresh=True)
    assert "BTCUSD" not in config.symbols
    assert "XAUUSD" in config.symbols, "les autres instruments restent surveilles"


async def test_un_instrument_non_surveille_ne_produit_aucune_decision(session) -> None:
    """On n'ecarte pas ce qui n'est pas dans la liste : la decision serait vide."""
    for index in range(10):
        entree = EntryType.MARKET if index % 2 else EntryType.STOP
        await _denoue(session, "AUTREUSD", entree)

    assert _bannissements(await learning.review(session, WatcherConfig())) == []


async def test_les_signaux_d_une_version_precedente_sont_ignores(session) -> None:
    """Leur resultat vient d'une comptabilite qui n'est plus la bonne.

    Les 21 operations denouees avant le 15/09/2026 etaient mesurees « sur
    position entiere » : un signal qui avait touche TP1 puis reflue y vaut
    -1 R plein, alors que la position reelle avait encaisse 40 %. Apprendre
    sur ces chiffres, c'est apprendre sur du faux -- precisement ce que le
    spec interdit.
    """
    for _ in range(10):
        await _denoue(
            session, "BREAKUSD", EntryType.BREAKOUT, version="market_watcher_v1.0"
        )

    assert _bannissements(await learning.review(session, WatcherConfig())) == []


async def test_une_position_reelle_gagnante_empeche_le_bannissement(session) -> None:
    """Le compte prime sur le suivi : c'est lui qui dit ce que l'argent a fait.

    Le suivi ne modelise pas le trailing : son resultat est un plancher du
    resultat reel. Un signal inscrit perdant peut donc correspondre a une
    position sortie en gain une fois le stop remonte. Bannir sur le plancher
    ecarterait un type d'entree qui gagne vraiment.
    """
    from app.models.enums import Direction, ExecutionMode, PositionState
    from app.models.trading import TradeRecord

    for index in range(10):
        await _denoue(session, "BREAKUSD", EntryType.BREAKOUT)
        if index == 0:
            # Une seule position reellement gagnante suffit.
            session.add(
                TradeRecord(
                    ticket=70000 + index,
                    symbol="BREAKUSD",
                    direction=Direction.BUY,
                    state=PositionState.CLOSED,
                    execution_mode=ExecutionMode.MT5_DEMO,
                    realized_pnl=12.40,
                    opened_at=utcnow(),
                )
            )
            await session.flush()

    assert _bannissements(await learning.review(session, WatcherConfig())) == []


async def test_un_seul_gain_suffit_a_ne_rien_ecarter(session) -> None:
    """Une clef qui a gagne une fois n'est pas sterile."""
    for _ in range(9):
        await _denoue(session, "BREAKUSD", EntryType.BREAKOUT)
    await _denoue(session, "BREAKUSD", EntryType.BREAKOUT, result_r=3.0)

    assert _bannissements(await learning.review(session, WatcherConfig())) == []


async def test_apprentissage_coupe_ne_decide_rien(session) -> None:
    for _ in range(10):
        await _denoue(session, "BREAKUSD", EntryType.BREAKOUT)
    config = WatcherConfig()
    config.learning_enabled = False

    assert _bannissements(await learning.review(session, config)) == []


def test_un_parametre_sans_borne_declaree_n_est_pas_ecrit() -> None:
    """Regle 2 du spec : une borne absente vaut interdiction d'ecrire."""
    config = WatcherConfig()
    config.learning_bounds = {}

    assert learning.clamp(config, "minimum_score", 95.0) is None


def test_une_valeur_est_ramenee_dans_ses_bornes() -> None:
    config = WatcherConfig()
    config.learning_bounds = {"minimum_score": [65.0, 80.0]}

    assert learning.clamp(config, "minimum_score", 95.0) == pytest.approx(80.0)
    assert learning.clamp(config, "minimum_score", 10.0) == pytest.approx(65.0)
    assert learning.clamp(config, "minimum_score", 72.0) == pytest.approx(72.0)


def test_les_bornes_du_yaml_survivent_a_la_conversion() -> None:
    """Les valeurs sont des listes, pas des nombres : la conversion doit suivre."""
    from app.watcher.config import _coerce

    converti = _coerce("learning_bounds", {"minimum_score": [65, 80]}, {})

    assert converti == {"minimum_score": [65.0, 80.0]}
