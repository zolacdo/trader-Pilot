"""Services Telegram : session utilisateur, decouverte de canaux, ecoute temps reel.

Le singleton ``telegram_service`` est partage par l'API, l'ecouteur et les
fonctions de decouverte. Sa construction n'ouvre aucune connexion et ne touche
ni au disque ni a la base : le Bridge demarre meme sans Telegram configure.
"""

from __future__ import annotations

from app.services.telegram.client import (
    TelegramFloodError,
    TelegramLoginError,
    TelegramNotConnectedError,
    TelegramService,
    TelegramServiceError,
)
from app.services.telegram.discovery import (
    fetch_history,
    join_channel,
    leave_channel,
    resolve_channel,
    search_channels,
)
from app.services.telegram.listener import ChannelListener, MessageCallback

telegram_service = TelegramService()

__all__ = [
    "ChannelListener",
    "MessageCallback",
    "TelegramFloodError",
    "TelegramLoginError",
    "TelegramNotConnectedError",
    "TelegramService",
    "TelegramServiceError",
    "fetch_history",
    "join_channel",
    "leave_channel",
    "resolve_channel",
    "search_channels",
    "telegram_service",
]
