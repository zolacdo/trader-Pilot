"""Decouverte de canaux Telegram publics : recherche, resolution, historique.

Toutes les fonctions prennent le service Telegram en premier argument afin de
partager la meme session utilisateur. Aucune action d'adhesion n'est declenchee
automatiquement : ``join_channel`` et ``leave_channel`` sont reservees a une
action explicite de l'utilisateur depuis l'application mobile.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl import functions, types

from app.config.logging_config import get_logger
from app.services.telegram.client import (
    TelegramFloodError,
    TelegramService,
    TelegramServiceError,
)

logger = get_logger(__name__)

# Au-dela de ce nombre de resultats on n'appelle plus GetFullChannelRequest
# (une requete par canal : trop couteux et source de FloodWait).
DESCRIPTION_LOOKUP_THRESHOLD = 8
DIALOG_SCAN_LIMIT = 200
MAX_SEARCH_LIMIT = 100

# Apercu du contenu d'un canal : combien de messages recents ressemblent a des
# signaux exploitables. Sans cette mesure, l'utilisateur n'a aucun element pour
# choisir un canal (CDC section 12).
PREVIEW_SAMPLE = 30
# Telegram limite les requetes : on interroge quelques canaux a la fois.
PREVIEW_CONCURRENCY = 4

_LINK_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:s/)?(?P<name>[A-Za-z0-9_]{3,32})/?$",
    re.IGNORECASE,
)
_USERNAME_PATTERN = re.compile(r"^@?(?P<name>[A-Za-z0-9_]{3,32})$")


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------
async def search_channels(
    service: TelegramService, query: str, limit: int = 30
) -> list[dict[str, Any]]:
    """Recherche globale de canaux publics, enrichie des canaux deja rejoints.

    Leve ``TelegramFloodError`` (message francais + delai) si Telegram impose une
    temporisation : la requete n'attend jamais, le serveur reste disponible.
    """
    client = service.require_client()
    cleaned = (query or "").strip().lstrip("@")
    if not cleaned:
        return []
    wanted = max(1, min(int(limit), MAX_SEARCH_LIMIT))
    try:
        found = await client(functions.contacts.SearchRequest(q=cleaned, limit=wanted))
    except FloodWaitError as exc:
        logger.warning("Recherche Telegram limitee (FloodWait %ss)", exc.seconds)
        raise TelegramFloodError(exc.seconds) from exc
    except Exception as exc:
        logger.error("Recherche Telegram impossible : %s", type(exc).__name__)
        raise TelegramServiceError("Recherche Telegram impossible pour le moment.") from exc

    joined = await _joined_dialogs(client)
    chats = [chat for chat in getattr(found, "chats", []) if _is_channel(chat)][:wanted]
    with_description = len(chats) <= DESCRIPTION_LOOKUP_THRESHOLD

    # Les apercus sont independants les uns des autres : on les calcule en
    # parallele, mais par petits groupes pour ne pas declencher de FloodWait.
    semaphore = asyncio.Semaphore(PREVIEW_CONCURRENCY)

    async def describe(chat: Any) -> dict[str, Any]:
        async with semaphore:
            return await _describe_chat(client, chat, joined, with_description, with_preview=True)

    return list(await asyncio.gather(*(describe(chat) for chat in chats)))


async def resolve_channel(service: TelegramService, username_or_link: str | int) -> dict | None:
    """Resout ``@nom``, ``https://t.me/nom``, ``t.me/nom`` ou un id numerique."""
    client = service.require_client()
    reference = _normalize_reference(username_or_link)
    if reference is None:
        return None
    try:
        entity = await client.get_entity(reference)
    except FloodWaitError as exc:
        raise TelegramFloodError(exc.seconds) from exc
    except Exception:
        logger.info("Canal Telegram introuvable pour la reference fournie")
        return None
    if not _is_channel(entity):
        return None
    joined = await _joined_dialogs(client)
    return await _describe_chat(client, entity, joined, with_description=True)


# ---------------------------------------------------------------------------
# Adhesion : uniquement sur action explicite de l'utilisateur
# ---------------------------------------------------------------------------
async def join_channel(service: TelegramService, channel_id: int | str) -> dict[str, Any]:
    """Rejoint un canal.

    ATTENTION : cette fonction ne doit JAMAIS etre appelee automatiquement
    (ni par la recherche, ni par l'analyse, ni au demarrage). Elle repond
    uniquement a une action explicite de l'utilisateur.
    """
    client = service.require_client()
    entity = await _entity(client, channel_id)
    try:
        await client(functions.channels.JoinChannelRequest(entity))
    except FloodWaitError as exc:
        raise TelegramFloodError(exc.seconds) from exc
    except Exception as exc:
        logger.error("Adhesion au canal impossible : %s", type(exc).__name__)
        raise TelegramServiceError("Impossible de rejoindre ce canal Telegram.") from exc
    logger.info("Canal Telegram rejoint : %s", utils.get_peer_id(entity))
    return {"id": utils.get_peer_id(entity), "joined": True}


async def leave_channel(service: TelegramService, channel_id: int | str) -> dict[str, Any]:
    """Quitte un canal.

    ATTENTION : jamais appelee automatiquement. Seule une action explicite de
    l'utilisateur peut declencher un depart de canal.
    """
    client = service.require_client()
    entity = await _entity(client, channel_id)
    try:
        await client(functions.channels.LeaveChannelRequest(entity))
    except FloodWaitError as exc:
        raise TelegramFloodError(exc.seconds) from exc
    except Exception as exc:
        logger.error("Depart du canal impossible : %s", type(exc).__name__)
        raise TelegramServiceError("Impossible de quitter ce canal Telegram.") from exc
    logger.info("Canal Telegram quitte : %s", utils.get_peer_id(entity))
    return {"id": utils.get_peer_id(entity), "joined": False}


# ---------------------------------------------------------------------------
# Historique
# ---------------------------------------------------------------------------
async def fetch_history(
    service: TelegramService, channel_id: int | str, limit: int
) -> list[dict[str, Any]]:
    """Recupere les N derniers messages texte accessibles (100 / 250 / 500...)."""
    client = service.require_client()
    entity = await _entity(client, channel_id)
    wanted = max(1, int(limit))
    messages: list[dict[str, Any]] = []
    try:
        async for message in client.iter_messages(entity, limit=wanted):
            text = (getattr(message, "message", "") or "").strip()
            if not text:
                continue  # media sans legende, service message : sans interet pour l'analyse
            reply_to = getattr(message, "reply_to", None)
            messages.append(
                {
                    "messageId": int(message.id),
                    "text": text,
                    "date": _as_utc(getattr(message, "date", None)),
                    "replyToMessageId": getattr(reply_to, "reply_to_msg_id", None),
                    "edited": getattr(message, "edit_date", None) is not None,
                }
            )
    except FloodWaitError as exc:
        logger.warning("Historique limite par Telegram (FloodWait %ss)", exc.seconds)
        raise TelegramFloodError(exc.seconds) from exc
    except Exception as exc:
        logger.error("Lecture de l'historique impossible : %s", type(exc).__name__)
        raise TelegramServiceError("Lecture de l'historique du canal impossible.") from exc
    return messages


# ---------------------------------------------------------------------------
# Outils internes
# ---------------------------------------------------------------------------
def _is_channel(chat: Any) -> bool:
    """Canaux de diffusion et supergroupes (types.ChannelForbidden est exclu)."""
    return isinstance(chat, types.Channel)


async def _joined_dialogs(client: TelegramClient) -> dict[int, dict[str, Any]]:
    """Canaux deja rejoints : id marque -> date du dernier message et dernier id."""
    joined: dict[int, dict[str, Any]] = {}
    try:
        dialogs = await client.get_dialogs(limit=DIALOG_SCAN_LIMIT)
    except FloodWaitError as exc:
        logger.warning("Liste des dialogues limitee (FloodWait %ss)", exc.seconds)
        return joined
    except Exception as exc:
        logger.warning("Liste des dialogues indisponible : %s", type(exc).__name__)
        return joined
    for dialog in dialogs:
        if not getattr(dialog, "is_channel", False):
            continue
        message = getattr(dialog, "message", None)
        joined[int(dialog.id)] = {
            "date": _as_utc(getattr(dialog, "date", None)),
            "last_id": getattr(message, "id", None),
        }
    return joined


async def _message_preview(client: TelegramClient, chat: Any) -> dict[str, Any] | None:
    """Echantillonne les derniers messages et compte ceux qui sont exploitables.

    Retourne ``None`` si le contenu n'est pas lisible : canal prive non rejoint,
    restriction Telegram ou temporisation. Aucune valeur n'est alors inventee,
    l'interface affiche l'explication.
    """
    from app.services.signals import deterministic_parser

    try:
        messages = await client.get_messages(chat, limit=PREVIEW_SAMPLE)
    except FloodWaitError as exc:
        logger.info("Apercu du canal limite (FloodWait %ss)", exc.seconds)
        return None
    except Exception as exc:
        logger.debug("Apercu du canal indisponible : %s", type(exc).__name__)
        return None

    if not messages:
        return None

    texts = [text for text in (getattr(m, "message", None) for m in messages) if text]
    signal_like = sum(1 for text in texts if deterministic_parser.parse(text).is_signal)
    last_date = getattr(messages[0], "date", None)

    return {
        "sampleSize": len(texts),
        "signalLikeCount": signal_like,
        "signalRate": round(signal_like / len(texts), 3) if texts else 0.0,
        "lastMessageAt": last_date,
    }


async def _describe_chat(
    client: TelegramClient,
    chat: Any,
    joined: dict[int, dict[str, Any]],
    with_description: bool,
    with_preview: bool = False,
) -> dict[str, Any]:
    """Normalise un canal Telegram en dictionnaire pret pour l'API."""
    peer_id = utils.get_peer_id(chat)
    info = joined.get(peer_id)
    username = getattr(chat, "username", None)
    members = getattr(chat, "participants_count", None)
    estimated = info.get("last_id") if info else None
    last_at = info.get("date") if info else None
    description: str | None = None

    if with_description:
        full = await _fetch_full(client, chat)
        if full is not None:
            description = (getattr(full, "about", "") or "").strip() or None
            members = getattr(full, "participants_count", None) or members
            estimated = estimated or getattr(full, "read_inbox_max_id", None) or None

    # Un canal prive jamais rejoint n'expose pas ses messages : inutile
    # d'interroger Telegram pour rien, et il faut le dire a l'utilisateur.
    readable = bool(username) or info is not None
    preview: dict[str, Any] | None = None
    preview_reason: str | None = None
    if with_preview:
        if readable:
            preview = await _message_preview(client, chat)
            if preview is None:
                preview_reason = (
                    "Contenu non lisible pour le moment : restriction du canal "
                    "ou quota Telegram atteint."
                )
            else:
                last_at = preview.get("lastMessageAt") or last_at
        else:
            preview_reason = (
                "Canal privé : son contenu reste illisible tant que vous ne l'avez pas rejoint."
            )

    return {
        "id": peer_id,
        "username": username,
        "title": getattr(chat, "title", "") or "",
        "description": description,
        "membersCount": members,
        "isPublic": bool(username),
        "alreadyJoined": info is not None,
        "lastMessageAt": last_at,
        "estimatedMessages": estimated,
        "sampleSize": preview.get("sampleSize") if preview else None,
        "signalLikeCount": preview.get("signalLikeCount") if preview else None,
        "signalRate": preview.get("signalRate") if preview else None,
        "previewAvailable": preview is not None,
        "previewReason": preview_reason,
    }


async def _fetch_full(client: TelegramClient, chat: Any) -> Any | None:
    """Details complets d'un canal. Enrichissement optionnel : jamais bloquant."""
    try:
        full = await client(functions.channels.GetFullChannelRequest(chat))
    except FloodWaitError as exc:
        logger.warning("Details du canal limites (FloodWait %ss)", exc.seconds)
        return None
    except Exception as exc:
        logger.debug("Details du canal indisponibles : %s", type(exc).__name__)
        return None
    return getattr(full, "full_chat", None)


def _normalize_reference(value: int | str | None) -> int | str | None:
    """Transforme une saisie utilisateur en reference exploitable par Telethon."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    link = _LINK_PATTERN.match(raw)
    if link:
        return f"@{link.group('name')}"
    if raw.lstrip("-").isdigit():
        return int(raw)
    name = _USERNAME_PATTERN.match(raw)
    if name:
        return f"@{name.group('name')}"
    return raw


async def _entity(client: TelegramClient, reference: int | str) -> Any:
    """Resolution d'entite, avec repli sur un PeerChannel pour les ids marques."""
    normalized = _normalize_reference(reference)
    if normalized is None:
        raise TelegramServiceError("Reference de canal Telegram invalide.")
    try:
        return await client.get_entity(normalized)
    except FloodWaitError as exc:
        raise TelegramFloodError(exc.seconds) from exc
    except Exception as exc:
        if isinstance(normalized, int):
            try:
                real_id, peer_class = utils.resolve_id(normalized)
                return await client.get_entity(peer_class(real_id))
            except Exception:
                logger.debug("Repli PeerChannel infructueux")
        raise TelegramServiceError("Canal Telegram introuvable ou inaccessible.") from exc


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
