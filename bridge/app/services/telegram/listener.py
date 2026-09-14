"""Ecoute temps reel des canaux Telegram surveilles.

Chaque message recu est persiste une seule fois (contrainte d'unicite
``channel_id`` + ``message_id``) puis transmis au callback fourni par
l'appelant. Le pipeline d'analyse des signaux est branche ailleurs : ce module
ne fait que capter, dedupliquer et relayer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from telethon import events

from app.config.logging_config import get_logger
from app.database.session import session_scope
from app.models.core import utcnow
from app.models.telegram import Channel, TelegramMessage
from app.services.telegram.client import TelegramService

logger = get_logger(__name__)

# (id interne du canal, payload du message) -> traitement asynchrone externe
MessageCallback = Callable[[int, dict[str, Any]], Awaitable[None]]

MARKED_ID_PREFIX = "-100"

# Rattrapage : nombre de messages relus par canal a chaque passage.
CATCHUP_LIMIT = 30
# Un message plus vieux que cette fenetre est enregistre mais jamais rejoue
# vers le pipeline. Rejouer un signal de la veille ouvrirait une position sur
# un prix qui n'existe plus ; le RiskManager le refuserait, mais il n'a pas a
# etre sollicite pour cela.
CATCHUP_MAX_AGE_SECONDS = 3600


class ChannelListener:
    """Abonnement aux nouveaux messages et aux editions des canaux surveilles."""

    def __init__(self, service: TelegramService, on_message: MessageCallback) -> None:
        self._service = service
        self._on_message = on_message
        # Toutes les variantes d'identifiant Telegram -> identifiant interne du canal.
        self._channels: dict[int, int] = {}
        self._monitored_count = 0
        self._registered = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Enregistre les handlers Telethon et charge la liste des canaux."""
        client = self._service.require_client()
        await self.refresh_subscriptions()
        if self._registered:
            return
        # Un seul handler global, filtre en interne : ainsi l'activation ou la
        # desactivation d'un canal ne necessite aucun reenregistrement Telethon.
        client.add_event_handler(self._on_new_message, events.NewMessage())
        client.add_event_handler(self._on_edited_message, events.MessageEdited())
        self._registered = True
        logger.info("Ecoute Telegram active sur %d canaux surveilles", self._monitored_count)

    async def stop(self) -> None:
        """Retire les handlers sans fermer la session Telegram."""
        client = self._service.client
        if client is not None and self._registered:
            try:
                client.remove_event_handler(self._on_new_message)
                client.remove_event_handler(self._on_edited_message)
            except Exception:
                logger.debug("Retrait des handlers Telegram ignore")
        self._registered = False
        logger.info("Ecoute Telegram arretee")

    async def refresh_subscriptions(self) -> None:
        """Recharge les canaux ``monitored`` (activation/desactivation utilisateur)."""
        async with self._lock:
            mapping: dict[int, int] = {}
            count = 0
            try:
                async with session_scope() as session:
                    result = await session.exec(select(Channel).where(Channel.monitored == True))
                    for channel in result.all():
                        if channel.id is None:
                            continue
                        count += 1
                        for variant in _id_variants(int(channel.telegram_id)):
                            mapping[variant] = int(channel.id)
            except Exception:
                logger.warning("Rechargement des canaux surveilles impossible")
                return
            self._channels = mapping
            self._monitored_count = count
            logger.info("Canaux surveilles : %d", count)

    @property
    def monitored_count(self) -> int:
        return self._monitored_count

    # ------------------------------------------------------------------
    # Handlers Telethon
    # ------------------------------------------------------------------
    async def _on_new_message(self, event: Any) -> None:
        await self._handle(event, edited=False)

    async def _on_edited_message(self, event: Any) -> None:
        await self._handle(event, edited=True)

    async def _handle(self, event: Any, edited: bool) -> None:
        """Filtre, persiste puis relaie. Ne leve jamais : l'ecoute doit survivre."""
        try:
            chat_id = getattr(event, "chat_id", None)
            if chat_id is None:
                return
            channel_id = self._channels.get(int(chat_id))
            if channel_id is None:
                return  # canal non surveille
            message = getattr(event, "message", None)
            text = (getattr(message, "message", "") or "").strip()
            if not text:
                return
            payload = _build_payload(message, text, edited)
            if not await self._persist(channel_id, payload):
                return  # doublon : deja recu et deja traite
            await self._dispatch(channel_id, payload)
        except Exception:
            logger.exception("Erreur de traitement d'un message Telegram")

    # ------------------------------------------------------------------
    # Persistance
    # ------------------------------------------------------------------
    async def _persist(self, channel_id: int, payload: dict[str, Any]) -> bool:
        """Insere le message si necessaire. False = doublon, rien a relayer.

        La contrainte d'unicite (channel_id, message_id) est verifiee par un
        SELECT prealable ET par un filet ``IntegrityError`` : un message rejoue
        apres reconnexion n'est jamais insere deux fois.
        """
        message_id = int(payload["messageId"])
        message_date = payload["date"] or utcnow()
        try:
            async with session_scope() as session:
                result = await session.exec(
                    select(TelegramMessage).where(
                        TelegramMessage.channel_id == channel_id,
                        TelegramMessage.message_id == message_id,
                    )
                )
                record = result.first()
                if record is not None:
                    if not payload["edited"] or record.text == payload["text"]:
                        return False
                    record.text = payload["text"]
                    record.edited = True
                    record.processed = False
                    session.add(record)
                else:
                    session.add(
                        TelegramMessage(
                            channel_id=channel_id,
                            message_id=message_id,
                            reply_to_message_id=payload["replyToMessageId"],
                            text=payload["text"],
                            message_date=message_date,
                            edited=bool(payload["edited"]),
                            processed=False,
                            # Message temps reel : jamais confondu avec l'historique.
                            is_historical=False,
                        )
                    )
                channel = await session.get(Channel, channel_id)
                if channel is not None:
                    channel.last_message_at = message_date
                    previous = channel.last_seen_message_id or 0
                    channel.last_seen_message_id = max(previous, message_id)
                    session.add(channel)
            return True
        except IntegrityError:
            logger.debug("Message Telegram deja enregistre (canal %s)", channel_id)
            return False

    # ------------------------------------------------------------------
    # Rattrapage
    # ------------------------------------------------------------------
    async def catch_up(self, limit: int = CATCHUP_LIMIT) -> int:
        """Relit l'historique recent et traite ce que le flux n'a pas rendu.

        Le flux d'updates Telegram n'est pas un contrat de livraison : une
        reconnexion, une coupure reseau ou un message publie par la session
        elle-meme peuvent ne jamais produire d'evenement. Sans relecture, ces
        messages sont perdus definitivement -- et avec eux les signaux qu'ils
        portaient.

        La deduplication est celle de l'ecoute temps reel : un message deja
        enregistre n'est jamais rejoue. Rend le nombre de messages rattrapes.
        """
        client = self._service.client
        if client is None:
            return 0

        rattrapes = 0
        for channel in await self._monitored_channels():
            try:
                rattrapes += await self._catch_up_channel(client, channel, limit)
            except Exception:
                logger.exception("Rattrapage impossible sur le canal %s", channel.id)
        if rattrapes:
            logger.info("Rattrapage Telegram : %d message(s) recuperes", rattrapes)
        return rattrapes

    async def _monitored_channels(self) -> list[Channel]:
        try:
            async with session_scope() as session:
                result = await session.exec(select(Channel).where(Channel.monitored == True))
                return [c for c in result.all() if c.id is not None]
        except Exception:
            logger.warning("Lecture des canaux surveilles impossible pour le rattrapage")
            return []

    async def _catch_up_channel(self, client: Any, channel: Channel, limit: int) -> int:
        """Relit un canal. Le premier passage ne fait qu'amorcer le curseur.

        Sans cet amorcage, activer un canal declencherait l'analyse de tout son
        historique recent d'un seul coup.
        """
        connu = int(channel.last_seen_message_id or 0)
        messages = await client.get_messages(int(channel.telegram_id), limit=limit)
        if not messages:
            return 0

        if connu == 0:
            await self._prime_cursor(channel, max(int(m.id) for m in messages))
            return 0

        maintenant = utcnow()
        rattrapes = 0
        # Du plus ancien au plus recent : l'ordre des signaux compte, un
        # message de suivi doit arriver apres le signal qu'il modifie.
        for message in sorted(messages, key=lambda m: int(m.id)):
            if int(message.id) <= connu:
                continue
            text = (getattr(message, "message", "") or "").strip()
            if not text:
                continue
            payload = _build_payload(message, text, edited=False)
            if not await self._persist(int(channel.id), payload):
                continue
            rattrapes += 1
            date = payload["date"]
            age = (maintenant - date).total_seconds() if date else None
            if age is not None and age > CATCHUP_MAX_AGE_SECONDS:
                logger.info(
                    "Message %s du canal %s enregistre sans analyse : %.0f min d'age",
                    message.id,
                    channel.id,
                    age / 60,
                )
                continue
            await self._dispatch(int(channel.id), payload)
        return rattrapes

    async def _prime_cursor(self, channel: Channel, dernier: int) -> None:
        """Pose le curseur sans analyser : l'historique n'est pas un flux."""
        async with session_scope() as session:
            enregistre = await session.get(Channel, int(channel.id))
            if enregistre is not None and not enregistre.last_seen_message_id:
                enregistre.last_seen_message_id = dernier
                session.add(enregistre)
        logger.info(
            "Curseur de rattrapage pose sur le canal %s au message %s", channel.id, dernier
        )

    async def _dispatch(self, channel_id: int, payload: dict[str, Any]) -> None:
        """Appelle le callback d'analyse sans jamais interrompre l'ecoute."""
        try:
            await self._on_message(channel_id, payload)
        except Exception:
            logger.exception("Le callback de traitement a echoue pour le canal %s", channel_id)


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------
def _build_payload(message: Any, text: str, edited: bool) -> dict[str, Any]:
    reply_to = getattr(message, "reply_to", None)
    return {
        "messageId": int(getattr(message, "id", 0)),
        "text": text,
        "date": _as_utc(getattr(message, "date", None)),
        "replyToMessageId": getattr(reply_to, "reply_to_msg_id", None),
        "edited": bool(edited or getattr(message, "edit_date", None) is not None),
    }


def _id_variants(telegram_id: int) -> set[int]:
    """Identifiants equivalents d'un canal : brut, negatif et forme -100xxx."""
    raw = abs(int(telegram_id))
    marked_prefix = MARKED_ID_PREFIX.lstrip("-")
    text = str(raw)
    if text.startswith(marked_prefix) and len(text) > len(marked_prefix) + 5:
        raw = int(text[len(marked_prefix) :])
    return {int(telegram_id), raw, -raw, int(f"{MARKED_ID_PREFIX}{raw}")}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
