"""Tests des routes de canaux qui dialoguent avec Telegram.

Telegram est remplace par un double : aucun appel reseau.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.api.v1 import channels as channels_api

PREFIX = "/api/v1"

CHANNEL_ID = -1002202904800
CHANNEL_USERNAME = "forex_signalsc"


@pytest.fixture
def telegram_double(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Simule Telegram : seul le nom d'utilisateur est resolvable.

    C'est exactement le comportement reel apres un redemarrage du Bridge :
    Telethon ne conserve pas son cache d'entites, donc un identifiant
    numerique ne designe plus rien tant que le canal n'a pas ete revu.
    """
    references: list[Any] = []

    async def fake_resolve(_service: Any, reference: Any) -> dict[str, Any] | None:
        references.append(reference)
        if isinstance(reference, str):
            return {
                "id": CHANNEL_ID,
                "username": CHANNEL_USERNAME,
                "title": "Forex Signals Trading",
                "description": None,
                "membersCount": 34066,
                "isPublic": True,
                "alreadyJoined": False,
                "lastMessageAt": None,
            }
        return None

    monkeypatch.setattr(channels_api, "resolve_channel", fake_resolve)
    return references


async def test_ajout_utilise_le_nom_plutot_que_l_identifiant(
    auth_client: AsyncClient, telegram_double: list[Any]
) -> None:
    """Regression : l'application envoyait l'identifiant seul et recevait 404."""
    response = await auth_client.post(
        f"{PREFIX}/channels",
        json={"telegramId": CHANNEL_ID, "username": CHANNEL_USERNAME, "join": False},
    )

    assert response.status_code == 201, response.text
    assert response.json()["title"] == "Forex Signals Trading"
    # Le nom doit avoir ete essaye en premier, pas l'identifiant.
    assert telegram_double[0] == CHANNEL_USERNAME


async def test_ajout_sans_nom_retombe_sur_l_identifiant(
    auth_client: AsyncClient, telegram_double: list[Any]
) -> None:
    """Un canal prive n'a pas de nom : l'identifiant reste le seul recours."""
    response = await auth_client.post(
        f"{PREFIX}/channels", json={"telegramId": CHANNEL_ID, "join": False}
    )

    assert response.status_code == 404
    assert telegram_double == [CHANNEL_ID]
    assert "introuvable" in response.json()["detail"].lower()


async def test_canal_ajoute_demarre_en_observation(
    auth_client: AsyncClient, telegram_double: list[Any]
) -> None:
    """Aucun canal ne peut trader des son ajout (CDC section 70)."""
    response = await auth_client.post(
        f"{PREFIX}/channels",
        json={"telegramId": CHANNEL_ID, "username": CHANNEL_USERNAME, "join": False},
    )
    assert response.status_code == 201

    payload = response.json()
    settings = payload.get("settings") or {}
    assert settings.get("mode") == "OBSERVE"
    assert payload.get("joined") is False
