"""Branchement de l'ecoute Telegram sur le moteur de trading.

Ce module fait le lien entre ``ChannelListener`` (reception) et
``TradingEngine`` (analyse, risque, execution). Il est volontairement mince :
la reception ne doit jamais dependre du trading, ni l'inverse.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from app.config.logging_config import get_logger
from app.database.session import session_scope
from app.models.core import utcnow
from app.repositories import channel_repo
from app.services import journal, runtime
from app.services.telegram import ChannelListener, telegram_service
from app.services.trading.engine import trading_engine

logger = get_logger(__name__)

channel_listener: ChannelListener | None = None
_catchup_task: asyncio.Task[None] | None = None

# Periode de relecture de l'historique. Assez courte pour qu'un signal manque
# reste exploitable, assez longue pour ne pas solliciter Telegram inutilement.
CATCHUP_INTERVAL_SECONDS = 120.0


async def _on_message(channel_id: int, payload: dict[str, Any]) -> None:
    """Analyse un message recu en temps reel et declenche le pipeline complet."""
    text = payload.get("text") or ""
    if not text.strip():
        return

    async with session_scope() as session:
        channel = await channel_repo.get(session, channel_id)
        if channel is None:
            logger.warning("Message recu pour un canal inconnu (%s)", channel_id)
            return

        outcome = await trading_engine.handle_message(
            session,
            text=text,
            channel=channel,
            message_id=payload.get("messageId"),
            message_date=payload.get("date"),
            reply_to_message_id=payload.get("replyToMessageId"),
        )

        if outcome.signal_id is not None:
            channel.last_signal_at = utcnow()
            if outcome.stage in {"executed", "observed", "needs_review"}:
                channel.signals_count += 1
            session.add(channel)

        runtime.runtime_state.last_signal_at = utcnow().isoformat()
        logger.info(
            "Message %s du canal %s : %s", payload.get("messageId"), channel.title, outcome.stage
        )


async def start_listener() -> ChannelListener | None:
    """Demarre l'ecoute si un compte Telegram est connecte."""
    global channel_listener
    if channel_listener is not None:
        return channel_listener
    if not telegram_service.connected:
        logger.info("Ecoute Telegram non demarree : aucun compte connecte")
        return None

    listener = ChannelListener(telegram_service, _on_message)
    try:
        await listener.start()
    except Exception as exc:
        logger.error("Impossible de demarrer l'ecoute Telegram : %s", exc)
        await journal.log(
            event="telegram_listener_failed",
            message=f"Ecoute Telegram indisponible : {exc}",
            category="telegram",
        )
        return None

    channel_listener = listener
    _start_catchup(listener)
    runtime.runtime_state.telegram_started = True
    await journal.log(
        event="telegram_listener_started",
        message=f"Ecoute active sur {listener.monitored_count} canal(aux)",
        category="telegram",
    )
    return listener


def _start_catchup(listener: ChannelListener) -> None:
    """Lance la relecture periodique de l'historique des canaux surveilles.

    Le flux d'updates Telegram n'est pas un contrat de livraison : mesure faite
    sur le canal de test, onze messages publies par la session elle-meme n'ont
    produit aucun evenement. Sans relecture, ces signaux etaient perdus.
    """
    global _catchup_task
    if _catchup_task is not None and not _catchup_task.done():
        return
    _catchup_task = asyncio.create_task(_catchup_loop(listener))


async def _catchup_loop(listener: ChannelListener) -> None:
    """Boucle de rattrapage. Une erreur ne doit jamais l'arreter."""
    while True:
        try:
            await asyncio.sleep(CATCHUP_INTERVAL_SECONDS)
            await listener.catch_up()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Cycle de rattrapage Telegram en echec")


async def stop_listener() -> None:
    global channel_listener, _catchup_task
    if _catchup_task is not None:
        _catchup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _catchup_task
        _catchup_task = None
    if channel_listener is None:
        return
    try:
        await channel_listener.stop()
    except Exception as exc:  # l'arret ne doit jamais bloquer la fermeture
        logger.warning("Arret de l'ecoute Telegram : %s", exc)
    channel_listener = None
    runtime.runtime_state.telegram_started = False


async def refresh_subscriptions() -> None:
    if channel_listener is not None:
        await channel_listener.refresh_subscriptions()
