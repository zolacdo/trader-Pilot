"""Un canal en observation doit pouvoir sortir de l'observation.

Verifie le 18/09/2026 : `SignalStatus.OBSERVED` n'apparaissait que dans sa
definition, dans la liste anti-doublon et a l'endroit qui l'ecrit. **Rien ne
denouait jamais un signal observe**, et aucun n'avait jamais existe en base
(411 REJECTED, 46 PARSED, 35 SENT, 12 OPEN, 2 FAILED, 1 CLOSED).

Mettre un canal en `OBSERVE` paraissait donc etre la facon prudente de
juger une source Telegram sans risquer d'argent. C'etait un aller sans
retour deguise en quarantaine : le canal se taisait et n'accumulait aucune
preuve permettant d'en sortir. La meme famille de defaut que
``disabled_entry_types`` ecrit et lu par personne, ou ``close_shadow_trade``
appele de nulle part.

Ce module donne une issue a chaque observation, sur les bougies REELLES, avec
les memes choix pessimistes que les deux suivis deja en place :

* quand une bougie contient le stop ET l'objectif, le stop l'emporte -- on ne
  sait pas lequel a ete touche en premier, et supposer l'inverse gonflerait
  une mesure sur laquelle on va decider de rouvrir un canal ;
* l'entree est supposee prise au moment du signal, sinon il n'y a pas
  d'observation, seulement une intention.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.enums import Direction, SignalStatus
from app.models.trading import Signal
from app.services.mt5.interface import Candle
from app.services.trading import observation_tracker
from tests.test_gestion_suivie_comme_executee import FakeCandleEngine

BASE = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)


def observation(**overrides: object) -> Signal:
    """Achat observe : entree 100, stop 98, objectif 104. Risque de 2."""
    values: dict[str, object] = {
        "idempotency_key": "obs-1",
        "raw_text": "BUY TESTUSD @100 SL 98 TP 104",
        "symbol": "TESTUSD",
        "broker_symbol": "TESTUSD",
        "direction": Direction.BUY,
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "take_profits": [104.0],
        "status": SignalStatus.OBSERVED,
        "received_at": BASE,
        "channel_id": None,
    }
    values.update(overrides)
    return Signal(**values)  # type: ignore[arg-type]


def candle(minute: int, low: float, high: float, close: float) -> Candle:
    return Candle(
        time=BASE + timedelta(minutes=minute),
        open=100.0,
        high=high,
        low=low,
        close=close,
        tick_volume=10,
    )


async def test_un_objectif_atteint_donne_un_resultat_positif(session) -> None:
    """Objectif a 104 pour un risque de 2 : +2 R."""
    signal = observation()
    session.add(signal)
    await session.flush()

    engine = FakeCandleEngine([candle(1, 99.5, 104.5, 104.2)])
    rapport = await observation_tracker.advance_observed_signals(
        session, engine, now=BASE + timedelta(minutes=5)
    )

    assert rapport.closed == 1
    assert signal.observed_result_r == 2.0
    assert signal.observed_closed_at is not None


async def test_un_stop_touche_donne_moins_un(session) -> None:
    signal = observation()
    session.add(signal)
    await session.flush()

    engine = FakeCandleEngine([candle(1, 97.5, 100.5, 98.0)])
    await observation_tracker.advance_observed_signals(
        session, engine, now=BASE + timedelta(minutes=5)
    )

    assert signal.observed_result_r == -1.0


async def test_une_bougie_qui_contient_les_deux_retient_le_stop(session) -> None:
    """Choix pessimiste : on ne sait pas lequel a ete touche en premier.

    Sans lui, cette mesure servirait a rouvrir un canal sur une statistique
    gonflee -- exactement ce qu'on cherche a eviter.
    """
    signal = observation()
    session.add(signal)
    await session.flush()

    engine = FakeCandleEngine([candle(1, 97.0, 105.0, 104.0)])
    await observation_tracker.advance_observed_signals(
        session, engine, now=BASE + timedelta(minutes=5)
    )

    assert signal.observed_result_r == -1.0


async def test_une_observation_qui_traine_est_chiffree_au_dernier_cours(session) -> None:
    """Passe l'age limite, elle est close : ouverte a vie, elle ne mesure rien."""
    signal = observation()
    session.add(signal)
    await session.flush()

    engine = FakeCandleEngine([candle(1, 99.0, 101.0, 101.0)])
    await observation_tracker.advance_observed_signals(
        session,
        engine,
        now=BASE + timedelta(hours=observation_tracker.MAX_AGE_HOURS + 1),
    )

    # Sortie a 101 pour une entree a 100 et un risque de 2 : +0,5 R.
    assert signal.observed_result_r == 0.5


async def test_une_observation_jeune_et_sans_issue_reste_ouverte(session) -> None:
    signal = observation()
    session.add(signal)
    await session.flush()

    engine = FakeCandleEngine([candle(1, 99.0, 101.0, 100.5)])
    rapport = await observation_tracker.advance_observed_signals(
        session, engine, now=BASE + timedelta(minutes=5)
    )

    assert rapport.closed == 0
    assert signal.observed_result_r is None


async def test_un_signal_sans_stop_n_est_pas_mesurable(session) -> None:
    """Sans stop, le R n'existe pas : on n'invente pas un resultat."""
    signal = observation(stop_loss=None, idempotency_key="obs-sans-stop")
    session.add(signal)
    await session.flush()

    engine = FakeCandleEngine([candle(1, 97.0, 105.0, 104.0)])
    rapport = await observation_tracker.advance_observed_signals(
        session, engine, now=BASE + timedelta(minutes=5)
    )

    assert rapport.closed == 0
    assert signal.observed_result_r is None


async def test_une_observation_deja_denouee_n_est_pas_reprise(session) -> None:
    """Le suivi ne doit pas reecrire un resultat deja inscrit."""
    signal = observation(observed_result_r=1.5, observed_closed_at=BASE)
    session.add(signal)
    await session.flush()

    engine = FakeCandleEngine([candle(1, 97.0, 100.5, 98.0)])
    rapport = await observation_tracker.advance_observed_signals(
        session, engine, now=BASE + timedelta(minutes=5)
    )

    assert rapport.checked == 0
    assert signal.observed_result_r == 1.5


async def test_une_vente_est_mesuree_dans_son_sens(session) -> None:
    """Une vente gagne quand le prix descend : le sens ne doit pas s'inverser."""
    signal = observation(
        direction=Direction.SELL,
        entry_price=100.0,
        stop_loss=102.0,
        take_profits=[96.0],
        idempotency_key="obs-vente",
    )
    session.add(signal)
    await session.flush()

    engine = FakeCandleEngine([candle(1, 95.5, 100.5, 96.0)])
    await observation_tracker.advance_observed_signals(
        session, engine, now=BASE + timedelta(minutes=5)
    )

    assert signal.observed_result_r == 2.0
