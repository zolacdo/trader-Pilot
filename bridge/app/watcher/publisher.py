"""Publication des messages du Market Watcher dans un canal Telegram.

Le Bridge dispose deja d'une session utilisateur Telegram (MTProto) : c'est
elle qui publie, ce qui evite de creer un bot, de generer un jeton et de
l'ajouter comme administrateur. Le canal cible est designe par son titre
— « tradepilot test » par defaut — et resolu parmi les conversations du
compte au premier envoi, puis memorise par son identifiant.

Deux garde-fous, dans cet ordre :

* le mode ``dry_run`` empeche tout envoi tout en laissant l'analyse tourner ;
* aucun canal n'est rejoint automatiquement. Si le canal n'existe pas dans le
  compte, le publieur le dit et n'envoie rien.

Les tests injectent leur propre fonction d'envoi : la suite ne doit jamais
faire partir un vrai message (CDC3 section 61).
"""

from __future__ import annotations

import asyncio
import time
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.telegram import PublishedMessage
from app.repositories import settings_repo
from app.services.telegram import telegram_service
from app.services.telegram.client import TelegramFloodError, TelegramServiceError
from app.watcher.config import SETTING_PREFIX, WatcherConfig

logger = get_logger(__name__)

# Nombre maximal de conversations parcourues pour retrouver le canal par titre.
DIALOG_SCAN_LIMIT = 400
# Intervalle minimal entre deux messages : Telegram limite fortement les
# publications rapprochees, et une rafale ferait taire le canal une heure.
MIN_INTERVAL_SECONDS = 1.5
# Telegram refuse les messages au-dela de cette longueur.
MAX_MESSAGE_LENGTH = 4000
# Nombre de tentatives apres une temporisation imposee par Telegram.
FLOOD_RETRIES = 1
# Au-dela, on renonce : attendre plus longtemps qu'un cycle d'analyse n'a
# aucun interet, le message serait perime a l'arrivee.
MAX_FLOOD_WAIT_SECONDS = 120

SETTING_CHANNEL_ID = f"{SETTING_PREFIX}telegram_channel_id"

Sender = Callable[[str], Awaitable[int | None]]


class ChannelNotFound(RuntimeError):
    """Le canal demande n'existe pas parmi les conversations du compte."""


class ChannelNotWritable(RuntimeError):
    """Le canal existe mais le compte n'a pas le droit d'y publier."""


@dataclass(slots=True)
class PublishResult:
    """Ce qui s'est reellement passe. ``sent`` faux n'est jamais une erreur fatale."""

    sent: bool = False
    message_id: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"sent": self.sent, "messageId": self.message_id, "reason": self.reason}


@dataclass(slots=True)
class ChannelTarget:
    """Canal resolu, tel qu'il sera affiche dans le diagnostic."""

    identifier: int
    title: str
    username: str | None = None
    writable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "title": self.title,
            "username": self.username,
            "writable": self.writable,
        }


def _fold(text: str) -> str:
    """Compare des titres sans se soucier des accents ni de la casse."""
    normalised = unicodedata.normalize("NFKD", (text or "").strip().lower())
    return "".join(char for char in normalised if not unicodedata.combining(char))


class TelegramPublisher:
    """Resout le canal cible une fois, puis y publie les messages du watcher."""

    def __init__(self, sender: Sender | None = None) -> None:
        self._sender = sender
        self._target: ChannelTarget | None = None
        self._entity: Any = None
        self._last_sent_at: float = 0.0
        self._last_error: str | None = None
        self._sent_count = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Diagnostic
    # ------------------------------------------------------------------
    @property
    def target(self) -> ChannelTarget | None:
        return self._target

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def status(self) -> dict[str, Any]:
        return {
            "resolved": self._target is not None,
            "channel": self._target.to_dict() if self._target else None,
            "sentCount": self._sent_count,
            "lastError": self._last_error,
            "usesInjectedSender": self._sender is not None,
        }

    def forget(self) -> None:
        """Oublie le canal resolu (changement de configuration, tests)."""
        self._target = None
        self._entity = None

    # ------------------------------------------------------------------
    # Resolution du canal
    # ------------------------------------------------------------------
    async def resolve(
        self, session: AsyncSession, config: WatcherConfig, refresh: bool = False
    ) -> ChannelTarget:
        """Retrouve le canal cible. Leve une erreur explicite s'il est absent."""
        if self._target is not None and not refresh:
            return self._target
        if self._sender is not None:
            # Envoi injecte (tests) : aucune resolution Telegram n'a de sens.
            self._target = ChannelTarget(identifier=0, title=config.telegram_channel)
            return self._target

        client = telegram_service.require_client()
        reference: int | str | None = config.telegram_channel_id
        if reference is None:
            stored = await settings_repo.get_setting(session, SETTING_CHANNEL_ID, None)
            reference = int(stored) if stored is not None else None

        entity = None
        if reference is not None:
            entity = await self._entity_by_id(client, int(reference))
        if entity is None:
            entity = await self._entity_by_name(client, config.telegram_channel)
        if entity is None:
            raise ChannelNotFound(
                f"Aucun canal Telegram nomme « {config.telegram_channel} » dans ce compte. "
                "Creez-le, ou renseignez son identifiant dans le reglage "
                "watcher.telegram_channel."
            )

        from telethon import utils

        identifier = int(utils.get_peer_id(entity))
        target = ChannelTarget(
            identifier=identifier,
            title=str(getattr(entity, "title", config.telegram_channel)),
            username=getattr(entity, "username", None),
            writable=_can_post(entity),
        )
        if not target.writable:
            raise ChannelNotWritable(
                f"Le compte Telegram n'a pas le droit de publier dans « {target.title} ». "
                "Donnez-lui les droits d'administration sur ce canal."
            )

        self._entity = entity
        self._target = target
        # L'identifiant est memorise : la prochaine resolution ne parcourra
        # plus les centaines de conversations du compte.
        await settings_repo.set_setting(session, SETTING_CHANNEL_ID, identifier)
        logger.info("Canal Telegram du watcher resolu : %s (%s)", target.title, identifier)
        return target

    async def _entity_by_id(self, client: Any, identifier: int) -> Any:
        try:
            return await client.get_entity(identifier)
        except Exception:
            # Un identifiant memorise peut devenir invalide : on retombe sur
            # la recherche par titre plutot que d'echouer.
            logger.debug("Identifiant de canal memorise inutilisable, recherche par titre")
            return None

    async def _entity_by_name(self, client: Any, reference: str) -> Any:
        """Resout @pseudo, un lien t.me, ou un titre de conversation."""
        cleaned = (reference or "").strip()
        if not cleaned:
            return None

        if cleaned.startswith("@") or cleaned.lower().startswith(("https://t.me/", "t.me/")):
            try:
                return await client.get_entity(cleaned)
            except Exception as exc:
                logger.info("Canal Telegram introuvable par reference : %s", type(exc).__name__)
                return None

        wanted = _fold(cleaned)
        try:
            dialogs = await client.get_dialogs(limit=DIALOG_SCAN_LIMIT)
        except Exception as exc:
            logger.warning("Liste des conversations Telegram illisible : %s", type(exc).__name__)
            return None

        fallback = None
        for dialog in dialogs:
            title = _fold(getattr(dialog, "name", "") or getattr(dialog, "title", "") or "")
            if not title:
                continue
            if title == wanted:
                return dialog.entity
            if fallback is None and wanted in title:
                fallback = dialog.entity
        return fallback

    # ------------------------------------------------------------------
    # Publication
    # ------------------------------------------------------------------
    async def publish(
        self, session: AsyncSession, text: str, config: WatcherConfig
    ) -> PublishResult:
        """Envoie un message. Ne leve jamais : un echec d'envoi n'arrete rien."""
        if not text.strip():
            return PublishResult(reason="Message vide.")
        if config.dry_run:
            logger.info("Mode dry_run : message non publie (%s caracteres).", len(text))
            return PublishResult(reason="Mode dry_run : aucune publication.")

        payload = text if len(text) <= MAX_MESSAGE_LENGTH else text[: MAX_MESSAGE_LENGTH - 1] + "…"

        async with self._lock:
            try:
                await self.resolve(session, config)
            except (ChannelNotFound, ChannelNotWritable) as exc:
                self._last_error = str(exc)
                logger.warning("Publication impossible : %s", exc)
                return PublishResult(reason=str(exc))
            except TelegramServiceError as exc:
                self._last_error = str(exc)
                logger.info("Telegram indisponible pour le watcher : %s", exc)
                return PublishResult(reason=str(exc))
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("Resolution du canal impossible : %s", exc)
                return PublishResult(reason=f"Resolution du canal impossible : {exc}")

            await self._respect_interval()
            result = await self._send_with_retry(payload)

        # Hors du verrou : l'ecriture en base ne doit pas retenir les autres
        # publications. Le canal de publication fait partie des canaux
        # surveilles ; sans cette trace, le Bridge relirait ce message comme un
        # signal entrant et rejouerait l'ordre qu'il vient de passer.
        if result.sent and result.message_id:
            await self._remember_published(session, result.message_id)
        return result

    async def _remember_published(self, session: AsyncSession, message_id: int) -> None:
        """Note l'identifiant du message que l'on vient de publier.

        Ne leve jamais : une trace manquante fait revenir le doublon, mais une
        exception ici ferait echouer une publication reussie.
        """
        target = self._target
        if target is None:
            return
        try:
            session.add(
                PublishedMessage(chat_id=int(target.identifier), message_id=int(message_id))
            )
            await session.flush()
        except Exception as exc:
            logger.warning(
                "Message %s non enregistre comme publication propre : %s", message_id, exc
            )

    async def _respect_interval(self) -> None:
        elapsed = time.monotonic() - self._last_sent_at
        if elapsed < MIN_INTERVAL_SECONDS:
            await asyncio.sleep(MIN_INTERVAL_SECONDS - elapsed)

    async def _send_with_retry(self, payload: str) -> PublishResult:
        for attempt in range(FLOOD_RETRIES + 1):
            try:
                message_id = await self._send(payload)
            except TelegramFloodError as exc:
                if attempt >= FLOOD_RETRIES or exc.seconds > MAX_FLOOD_WAIT_SECONDS:
                    self._last_error = str(exc)
                    logger.warning("Publication abandonnee : %s", exc)
                    return PublishResult(reason=str(exc))
                logger.info("Telegram impose %s s d'attente, nouvelle tentative", exc.seconds)
                await asyncio.sleep(exc.seconds + 1)
                continue
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("Envoi Telegram impossible : %s", exc)
                return PublishResult(reason=f"Envoi impossible : {exc}")

            self._last_sent_at = time.monotonic()
            self._sent_count += 1
            self._last_error = None
            return PublishResult(sent=True, message_id=message_id)
        return PublishResult(reason="Envoi abandonne apres temporisation Telegram.")

    async def _send(self, payload: str) -> int | None:
        """Envoi reel, ou envoi injecte pendant les tests."""
        if self._sender is not None:
            return await self._sender(payload)

        from telethon.errors import FloodWaitError

        client = telegram_service.require_client()
        entity = self._entity if self._entity is not None else self._target
        if entity is None:
            raise TelegramServiceError("Canal Telegram non resolu.")
        try:
            message = await client.send_message(
                entity, payload, parse_mode="html", link_preview=False
            )
        except FloodWaitError as exc:
            raise TelegramFloodError(exc.seconds) from exc
        return int(getattr(message, "id", 0)) or None


# Publieur partage par l'ordonnanceur et l'API. Sa construction n'ouvre aucune
# connexion : le Bridge demarre meme sans Telegram configure.
telegram_publisher = TelegramPublisher()


def _can_post(entity: Any) -> bool:
    """Le compte peut-il publier dans ce canal ?

    Un canal de diffusion exige les droits d'administration ; un groupe ou un
    supergroupe accepte les messages de ses membres. En cas de doute, on
    autorise la tentative : Telegram refusera clairement s'il le faut.
    """
    if getattr(entity, "creator", False):
        return True
    if getattr(entity, "admin_rights", None) is not None:
        return True
    broadcast = getattr(entity, "broadcast", False)
    megagroup = getattr(entity, "megagroup", False)
    # Un canal de diffusion pur sans droits : la publication echouerait.
    return not (broadcast and not megagroup)


__all__ = [
    "ChannelNotFound",
    "ChannelNotWritable",
    "ChannelTarget",
    "PublishResult",
    "Sender",
    "TelegramPublisher",
    "telegram_publisher",
]
