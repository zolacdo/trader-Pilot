"""Tests du service de tunnel ngrok.

Aucun appel reseau, aucun binaire lance : le processus et l'API locale de
ngrok sont simules.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from app.services.tunnel.ngrok_service import NgrokService

# Le paquet expose l'instance partagee sous le nom ``ngrok_service``, ce qui
# masque le module homonyme : un import classique renverrait l'objet, pas le
# module. importlib le recupere sans ambiguite.
tunnel_module = importlib.import_module("app.services.tunnel.ngrok_service")


class _FakeProcess:
    """Processus ngrok simule : se termine proprement a la demande."""

    def __init__(self) -> None:
        self.pid = 4242
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:  # pragma: no cover - seulement si terminate echoue
        self.killed = True

    def wait(self) -> int:
        return 0

    def poll(self) -> int | None:
        """None tant que le processus vit : le service surveille une sortie hative."""
        return 0 if self.terminated or self.killed else None


@pytest.fixture
def tunnel(monkeypatch: pytest.MonkeyPatch) -> NgrokService:
    """Service de tunnel dont le lancement de processus est neutralise."""
    service = NgrokService()
    process = _FakeProcess()

    monkeypatch.setattr(tunnel_module, "find_ngrok_binary", lambda settings=None: "ngrok.exe")
    monkeypatch.setattr(tunnel_module.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(tunnel_module, "attach_child", lambda _process: None)
    monkeypatch.setattr(tunnel_module, "close_job", lambda _job: None)
    # Raccourcit l'attente : le test ne doit pas durer 30 secondes.
    monkeypatch.setattr(tunnel_module, "STARTUP_TIMEOUT_SECONDS", 0.2)
    service._fake_process = process  # type: ignore[attr-defined]
    return service


async def _enable_tunnel(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "ngrok_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ngrok_domain", "exemple.ngrok-free.dev", raising=False)
    monkeypatch.setattr(settings, "ngrok_authtoken", "", raising=False)


async def test_tunnel_desactive_ne_lance_rien(tunnel: NgrokService) -> None:
    status = await tunnel.start()
    assert status.enabled is False
    assert status.running is False


async def test_echec_de_demarrage_ne_bloque_pas_le_bridge(
    tunnel: NgrokService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression : start() appelait stop(), qui reprenait le meme verrou.

    asyncio.Lock n'est pas reentrant : le Bridge restait fige pour toujours
    dans son demarrage des que ngrok tardait a publier son URL.
    """
    await _enable_tunnel(monkeypatch)

    async def jamais_d_url(timeout: float = 3.0) -> str | None:
        return None

    monkeypatch.setattr(tunnel_module, "read_public_url", jamais_d_url)

    status = await asyncio.wait_for(tunnel.start(), timeout=5)

    assert status.running is False
    assert status.error is not None
    assert tunnel._fake_process.terminated is True  # type: ignore[attr-defined]

    # Le verrou doit etre libre : un arret explicite ne doit pas se bloquer.
    await asyncio.wait_for(tunnel.stop(), timeout=5)


async def test_tunnel_existant_est_reutilise(
    tunnel: NgrokService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un agent ngrok deja lance n'est jamais double."""
    await _enable_tunnel(monkeypatch)

    async def url_existante(timeout: float = 3.0) -> str | None:
        return "https://exemple.ngrok-free.dev"

    monkeypatch.setattr(tunnel_module, "read_public_url", url_existante)

    status = await tunnel.start()

    assert status.running is True
    assert status.public_url == "https://exemple.ngrok-free.dev"
    assert status.managed_by_bridge is False
    assert tunnel._fake_process.terminated is False  # type: ignore[attr-defined]
