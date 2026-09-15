"""Scenarios de bout en bout du CDC (sections 82 a 87), joues en mode PAPER.

Aucun ordre reel n'est envoye : le moteur de trading est branche sur le
simulateur. Chaque scenario part d'un message Telegram brut et verifie
l'etat final du signal, des positions et du journal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.core import utcnow
from app.models.enums import (
    ChannelMode,
    Direction,
    ExecutionMode,
    PositionState,
    RejectionReason,
    SignalStatus,
)
from app.models.telegram import Channel
from app.repositories import channel_repo, settings_repo, signal_repo, trade_repo
from app.services.trading.engine import trading_engine
from app.services.trading.paper import PaperTradingService

SIGNAL_TEXT = "XAUUSD BUY\nENTRY 3320\nSL 3310\nTP1 3330\nTP2 3340"
ENTRY_BID = 3320.0
FILL_PRICE = 3320.20  # ask = bid + 20 points de spread


async def prepare(
    session: AsyncSession,
    paper: PaperTradingService,
    mode: ChannelMode = ChannelMode.AUTO,
    **risk_changes: object,
) -> Channel:
    """Canal surveille, trading automatique actif, cours aligne sur l'entree."""
    channel = await channel_repo.upsert(
        session, telegram_id=2001, title="Canal scenario", username="scenario"
    )
    assert channel.id is not None
    await channel_repo.update_settings(session, channel.id, {"mode": mode, "enabled": True})

    changes: dict[str, object] = {
        "auto_trading_enabled": True,
        "execution_mode": ExecutionMode.PAPER,
        # Ces scenarios horodatent leurs messages a l'heure REELLE, et les
        # reglages n'autorisent par defaut que le lundi au vendredi : la suite
        # entiere tombait donc en OUTSIDE_TRADING_DAYS les samedis et
        # dimanches, en laissant croire a une regression. Le garde-fou des
        # jours a son propre test dans test_risk_manager.py ; ici on ouvre les
        # sept jours pour que le chemin d'execution soit seul juge.
        "trading_days": [0, 1, 2, 3, 4, 5, 6],
    }
    changes.update(risk_changes)
    await settings_repo.update_risk_settings(session, changes)

    # Le prix simule est amene au niveau de l'entree : l'ordre part au marche.
    paper.set_price("XAUUSD", ENTRY_BID)
    return channel


# ---------------------------------------------------------------------------
# Section 82 : premier objectif end-to-end
# ---------------------------------------------------------------------------

async def test_scenario_82_signal_complet_execute_en_paper(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)

    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )

    assert outcome.stage == "executed", outcome.detail
    assert outcome.executed is True
    assert outcome.rejected is False

    # --- le signal a bien ete interprete ---
    signal = await signal_repo.get(session, outcome.signal_id)
    assert signal is not None
    assert signal.normalized_symbol == "XAUUSD"
    assert signal.broker_symbol == "XAUUSD"
    assert signal.direction is Direction.BUY
    assert signal.entry_price == 3320.0
    assert signal.stop_loss == 3310.0
    assert signal.take_profits == [3330.0, 3340.0]
    assert signal.confidence >= 0.85
    assert signal.status is SignalStatus.OPEN
    assert signal.execution_mode is ExecutionMode.PAPER

    # --- le lot a ete calcule par le RiskManager ---
    # 0.5 % de 10 000 = 50 USD ; 10 dollars de stop = 1000 USD/lot -> 0.05 lot
    assert signal.computed_lot == pytest.approx(0.05)
    assert signal.risk_amount == pytest.approx(50.0)
    # Le rendement se mesure sur la sortie reellement executee, pas sur TP1.
    # En PARTIAL_CLOSE (le defaut), la position est portee jusqu'a TP2 avec une
    # fermeture partielle a TP1 : (40 x 10 + 30 x 20) / 70 / 10 = 1,43.
    # Juge sur TP1 seul il valait 1,0, ce qui decrivait une sortie que le
    # systeme n'effectue pas.
    assert signal.risk_reward == pytest.approx(1.4286, abs=0.001)

    # --- la position existe dans le simulateur ---
    positions = await paper.positions()
    assert len(positions) == 1
    assert positions[0].volume == pytest.approx(0.05)
    assert positions[0].price_open == pytest.approx(FILL_PRICE)
    assert positions[0].stop_loss == pytest.approx(3310.0)
    assert positions[0].take_profit == pytest.approx(3340.0)

    # --- elle est suivie en base ---
    trades = await trade_repo.trades_for_signal(session, signal.id)
    assert len(trades) == 1
    assert trades[0].state is PositionState.OPEN
    assert trades[0].take_profit_targets == [3330.0, 3340.0]

    # --- la trace d'audit est complete ---
    stages = {event.stage for event in await signal_repo.events_for(session, signal.id)}
    assert {"parser", "risk", "order_check", "order_send", "execution"} <= stages


async def test_scenario_82_suite_tp1_hit_et_break_even(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)
    first = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )
    assert first.executed is True

    outcome = await trading_engine.handle_message(
        session,
        "TP1 HIT\nMOVE SL TO BE",
        channel=channel,
        message_id=2,
        message_date=utcnow(),
        reply_to_message_id=1,
    )

    assert outcome.stage == "follow_up"
    assert outcome.executed is True

    trades = await trade_repo.trades_for_signal(session, first.signal_id)
    trade = trades[0]
    assert trade.tp_index == 1
    assert trade.break_even_applied is True
    # Break even = prix d'ouverture decale de 5 points, soit 0.05 dollar.
    assert trade.stop_loss == pytest.approx(FILL_PRICE + 0.05)
    # Prise partielle de 40 % : 0.05 -> 0.02 ferme, 0.03 restant.
    assert trade.closed_volume == pytest.approx(0.02)
    assert trade.volume == pytest.approx(0.03)
    assert trade.state is PositionState.PARTIALLY_CLOSED

    position = (await paper.positions())[0]
    assert position.volume == pytest.approx(0.03)
    assert position.stop_loss == pytest.approx(FILL_PRICE + 0.05)


async def test_scenario_82_close_gold_ferme_la_position(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)
    first = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )
    assert first.executed is True

    outcome = await trading_engine.handle_message(
        session, "CLOSE GOLD NOW", channel=channel, message_id=2, message_date=utcnow()
    )

    assert outcome.stage == "follow_up"
    assert await paper.positions() == []
    trade = (await trade_repo.trades_for_signal(session, first.signal_id))[0]
    assert trade.state is PositionState.CLOSED
    assert trade.volume == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Section 83 : message de convivialite
# ---------------------------------------------------------------------------

async def test_scenario_83_message_de_convivialite_ne_cree_aucun_trade(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)

    outcome = await trading_engine.handle_message(
        session,
        "Gold is looking very bullish today \U0001f525",
        channel=channel,
        message_id=1,
        message_date=utcnow(),
    )

    assert outcome.executed is False
    assert outcome.stage in {"ignored", "no_action"}
    assert await paper.positions() == []
    assert await trade_repo.open_trades(session, ExecutionMode.PAPER) == []


async def test_scenario_83_bonjour_famille_ne_cree_aucun_trade(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)
    outcome = await trading_engine.handle_message(
        session, "GOOD MORNING FAMILY \U0001f525", channel=channel, message_id=1
    )
    assert outcome.executed is False
    assert await paper.positions() == []


# ---------------------------------------------------------------------------
# Section 84 : limite de perte journaliere
# ---------------------------------------------------------------------------

async def test_scenario_84_limite_de_perte_journaliere(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)

    state = await settings_repo.get_trading_state(session)
    state.day_key = settings_repo.today_key()
    state.day_start_balance = 10000.0
    state.day_realized_pnl = -400.0  # 4 % de perte pour une limite de 3 %
    await settings_repo.save_trading_state(session, state)

    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )

    assert outcome.rejected is True
    assert outcome.reason is RejectionReason.DAILY_LOSS_LIMIT
    signal = await signal_repo.get(session, outcome.signal_id)
    assert signal is not None
    assert signal.status is SignalStatus.REJECTED
    assert signal.rejection_reason is RejectionReason.DAILY_LOSS_LIMIT
    assert await paper.positions() == []


# ---------------------------------------------------------------------------
# Section 85 : message recu deux fois
# ---------------------------------------------------------------------------

async def test_scenario_85_doublon_ne_produit_qu_un_seul_trade(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)

    first = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )
    second = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )

    assert first.executed is True
    assert second.executed is False
    assert second.rejected is True
    assert second.reason is RejectionReason.DUPLICATE_SIGNAL
    assert len(await paper.positions()) == 1
    assert len(await signal_repo.list_signals(session, limit=50)) == 1


# ---------------------------------------------------------------------------
# Section 86 : signal ambigu, aucune IA disponible
# ---------------------------------------------------------------------------

async def test_scenario_86_signal_ambigu_est_rejete(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    """Stop loss du mauvais cote : le parser local refuse, aucun ordre ne part.

    Le refus est terminal. Rien n'attend l'utilisateur : le systeme tranche
    lui-meme et consigne le motif.
    """
    channel = await prepare(session, paper)

    outcome = await trading_engine.handle_message(
        session,
        "XAUUSD BUY 3320\nSL 3340\nTP 3350",
        channel=channel,
        message_id=1,
        message_date=utcnow(),
    )

    assert outcome.executed is False
    signal = await signal_repo.get(session, outcome.signal_id)
    assert signal is not None
    assert signal.status is SignalStatus.REJECTED
    assert await paper.positions() == []


async def test_scenario_86_signal_bien_structure_passe_sans_ia(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    """OpenRouter indisponible : le parser deterministe suffit."""
    from app.services.openrouter.service import openrouter_service

    assert openrouter_service.configured is False
    channel = await prepare(session, paper)
    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )
    assert outcome.executed is True


# ---------------------------------------------------------------------------
# Section 87 : vieux signal apres un redemarrage du Bridge
# ---------------------------------------------------------------------------

async def test_scenario_87_vieux_signal_n_est_jamais_envoye(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)

    outcome = await trading_engine.handle_message(
        session,
        SIGNAL_TEXT,
        channel=channel,
        message_id=1,
        message_date=datetime.now(UTC) - timedelta(minutes=10),
    )

    assert outcome.rejected is True
    assert outcome.reason is RejectionReason.SIGNAL_EXPIRED
    assert await paper.positions() == []


# ---------------------------------------------------------------------------
# Modes de canal
# ---------------------------------------------------------------------------

async def test_canal_en_observation_n_envoie_jamais_d_ordre(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper, mode=ChannelMode.OBSERVE)

    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )

    assert outcome.stage == "observed"
    assert outcome.executed is False
    signal = await signal_repo.get(session, outcome.signal_id)
    assert signal is not None
    assert signal.status is SignalStatus.OBSERVED
    assert await paper.positions() == []
    assert await trade_repo.open_trades(session, ExecutionMode.PAPER) == []


async def test_canal_manuel_demande_une_validation_puis_execute(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper, mode=ChannelMode.MANUAL)

    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )

    assert outcome.stage == "needs_review"
    assert outcome.executed is False
    signal = await signal_repo.get(session, outcome.signal_id)
    assert signal is not None
    assert signal.status is SignalStatus.NEEDS_REVIEW
    assert signal.expires_at is not None
    assert await paper.positions() == []

    approved = await trading_engine.approve_manually(session, signal.id)

    assert approved.executed is True
    assert approved.stage == "executed"
    refreshed = await signal_repo.get(session, signal.id)
    assert refreshed is not None
    assert refreshed.status is SignalStatus.OPEN
    assert refreshed.reviewed_at is not None
    assert len(await paper.positions()) == 1


async def test_validation_manuelle_d_un_signal_perime_est_refusee(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper, mode=ChannelMode.MANUAL)
    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )
    signal = await signal_repo.get(session, outcome.signal_id)
    assert signal is not None
    signal.expires_at = utcnow() - timedelta(seconds=1)
    await signal_repo.save(session, signal)

    approved = await trading_engine.approve_manually(session, signal.id)

    assert approved.rejected is True
    assert approved.reason is RejectionReason.SIGNAL_EXPIRED
    assert await paper.positions() == []


async def test_validation_manuelle_depuis_une_autre_session(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    """Regression : SQLite relit les dates sans fuseau horaire.

    L'application valide un signal depuis une requete HTTP ulterieure, donc
    depuis une session neuve. La date d'expiration doit revenir comparable a
    l'heure UTC, sans quoi la validation echouerait sur un ``TypeError``.

    Le fuseau est desormais reattache a la relecture par ``UtcDateTime`` :
    c'est ce qui permet aussi a l'API de publier des horodatages explicites,
    et donc au telephone de les afficher a la bonne heure.
    """
    from app.database.session import session_scope

    channel = await prepare(session, paper, mode=ChannelMode.MANUAL)
    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )
    signal_id = outcome.signal_id
    assert signal_id is not None
    await session.commit()

    async with session_scope() as autre_session:
        relu = await signal_repo.get(autre_session, signal_id)
        assert relu is not None
        assert relu.expires_at is not None
        # La date relue porte son fuseau : comparable telle quelle a utcnow().
        assert relu.expires_at.tzinfo is not None
        assert relu.expires_at > utcnow()

        approved = await trading_engine.approve_manually(autre_session, signal_id)

    assert approved.executed is True
    assert len(await paper.positions()) == 1


async def test_refus_manuel_d_un_signal(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper, mode=ChannelMode.MANUAL)
    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )

    rejected = await trading_engine.reject_manually(
        session, outcome.signal_id, "Je ne veux pas de ce trade"
    )

    assert rejected.rejected is True
    assert rejected.reason is RejectionReason.MANUAL_REJECTION
    signal = await signal_repo.get(session, outcome.signal_id)
    assert signal is not None
    assert signal.status is SignalStatus.REJECTED
    assert await paper.positions() == []


async def test_approbation_d_un_signal_inconnu(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    assert paper is not None
    outcome = await trading_engine.approve_manually(session, 999999)
    assert outcome.stage == "not_found"


# ---------------------------------------------------------------------------
# Pause, reprise et arret d'urgence
# ---------------------------------------------------------------------------

async def test_pause_bloque_les_nouveaux_signaux(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)
    await trading_engine.pause(session, "Test de pause")

    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )

    assert outcome.rejected is True
    assert outcome.reason is RejectionReason.TRADING_PAUSED
    assert await paper.positions() == []

    await trading_engine.resume(session)
    state = await settings_repo.get_trading_state(session)
    assert state.paused is False


async def test_arret_d_urgence_ferme_toutes_les_positions(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)
    await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )
    assert len(await paper.positions()) == 1

    result = await trading_engine.close_all_positions(session, suspend=True)

    assert result["ok"] is True
    assert result["closed"] == 1
    assert await paper.positions() == []
    state = await settings_repo.get_trading_state(session)
    assert state.paused is True


async def test_annulation_de_tous_les_ordres_en_attente(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)
    # Une entree tres eloignee du marche devient un ordre en attente.
    outcome = await trading_engine.handle_message(
        session,
        "XAUUSD BUY LIMIT 3280\nSL 3270\nTP 3320",
        channel=channel,
        message_id=1,
        message_date=utcnow(),
    )
    assert outcome.executed is True
    assert len(await paper.orders()) == 1

    result = await trading_engine.cancel_all_pending(session)

    assert result["ok"] is True
    assert result["cancelled"] == 1
    assert await paper.orders() == []


async def test_auto_trading_desactive_refuse_le_signal(
    session: AsyncSession, paper: PaperTradingService
) -> None:
    channel = await prepare(session, paper)
    await settings_repo.update_risk_settings(session, {"auto_trading_enabled": False})

    outcome = await trading_engine.handle_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, message_date=utcnow()
    )

    assert outcome.rejected is True
    assert outcome.reason is RejectionReason.AUTO_TRADING_OFF
    assert await paper.positions() == []
