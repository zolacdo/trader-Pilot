"""Tunnel ngrok : rend le Bridge joignable depuis le telephone hors du reseau local.

Le Bridge continue d'ecouter uniquement en local ; ngrok publie ce port sur un
domaine reserve stable, ce qui evite de reconfigurer l'application a chaque
redemarrage. Toutes les routes sensibles restent protegees par le jeton de
peripherique (CDC section 41) : le tunnel n'ouvre jamais un acces anonyme.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config.logging_config import get_logger, register_secret
from app.config.settings import Settings, get_settings
from app.services.events import EventType, event_bus
from app.services.win_job import attach_child, close_job

logger = get_logger(__name__)

NGROK_LOCAL_API = "http://127.0.0.1:4040/api/tunnels"
STARTUP_TIMEOUT_SECONDS = 30.0


@dataclass
class TunnelStatus:
    enabled: bool = False
    running: bool = False
    public_url: str | None = None
    domain: str | None = None
    error: str | None = None
    managed_by_bridge: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "publicUrl": self.public_url,
            "domain": self.domain,
            "error": self.error,
            "managedByBridge": self.managed_by_bridge,
        }


def default_config_path() -> Path | None:
    """Fichier de configuration ngrok de l'utilisateur, s'il existe.

    C'est lui qui contient l'authtoken enregistre par ``ngrok config
    add-authtoken``. Le Bridge ne le lit jamais : il se contente de le
    transmettre a ngrok.
    """
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        candidates = [Path(local) / "ngrok" / "ngrok.yml"] if local else []
    else:
        candidates = [
            Path.home() / ".config" / "ngrok" / "ngrok.yml",
            Path.home() / ".ngrok2" / "ngrok.yml",
        ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def find_ngrok_binary(settings: Settings | None = None) -> str | None:
    """Cherche ngrok dans la configuration, le PATH, puis DATA_DIR/bin."""
    settings = settings or get_settings()
    if settings.ngrok_binary:
        candidate = Path(settings.ngrok_binary)
        if candidate.exists():
            return str(candidate)
    found = shutil.which("ngrok")
    if found:
        return found
    local = settings.data_dir / "bin" / ("ngrok.exe" if os.name == "nt" else "ngrok")
    if local.exists():
        return str(local)
    if os.name == "nt":
        # Installation par le Microsoft Store : l'alias d'execution n'est pas
        # dans le PATH des shells non Windows mais reste lancable.
        alias = Path.home() / "AppData" / "Local" / "Microsoft" / "WindowsApps" / "ngrok.exe"
        if alias.exists():
            return str(alias)
    return None


async def read_public_url(timeout: float = 3.0) -> str | None:
    """Interroge l'API locale de ngrok pour obtenir l'URL publique reelle."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(NGROK_LOCAL_API)
            if response.status_code != 200:
                return None
            tunnels = response.json().get("tunnels") or []
    except (httpx.HTTPError, ValueError):
        return None

    https = [t.get("public_url") for t in tunnels if str(t.get("public_url", "")).startswith("https://")]
    if https:
        return https[0]
    return tunnels[0].get("public_url") if tunnels else None


class NgrokService:
    """Demarre et surveille le processus ngrok."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._job: int | None = None
        self._status = TunnelStatus()
        self._lock = asyncio.Lock()

    @property
    def status(self) -> TunnelStatus:
        return self._status

    async def start(self) -> TunnelStatus:
        settings = get_settings()
        self._status = TunnelStatus(enabled=settings.ngrok_enabled, domain=settings.ngrok_domain or None)

        if not settings.ngrok_enabled:
            logger.info("Tunnel ngrok desactive (NGROK_ENABLED=false)")
            return self._status

        async with self._lock:
            # Un tunnel deja actif (lance a la main ou par le service Windows)
            # est reutilise tel quel plutot que d'ouvrir un doublon.
            existing = await read_public_url()
            if existing:
                self._status.running = True
                self._status.public_url = existing
                self._status.managed_by_bridge = False
                logger.info("Tunnel ngrok deja actif : %s", existing)
                self._publish()
                return self._status

            binary = find_ngrok_binary(settings)
            if binary is None:
                self._status.error = (
                    "Binaire ngrok introuvable. Lancez scripts/install_bridge.ps1 -WithNgrok "
                    "ou renseignez NGROK_BINARY."
                )
                logger.warning(self._status.error)
                self._publish()
                return self._status

            if settings.ngrok_authtoken:
                register_secret(settings.ngrok_authtoken)
                await self._configure_token(binary, settings.ngrok_authtoken)

            command = self._build_command(binary, settings)
            logger.info("Demarrage du tunnel ngrok sur le port %s", settings.bridge_port)
            try:
                # Binaire choisi par l'utilisateur via NGROK_BINARY ou le PATH.
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                # Si le Bridge est tue brutalement, Windows tue aussi ngrok :
                # sinon le tunnel survivrait et bloquerait le demarrage suivant.
                self._job = attach_child(self._process)
            except OSError as exc:
                self._status.error = f"Impossible de lancer ngrok : {exc}"
                logger.error(self._status.error)
                self._publish()
                return self._status

            url = await self._wait_for_url()
            if url is None:
                self._status.error = (
                    "Le tunnel ngrok n'a pas repondu. Verifiez le token, le domaine reserve "
                    "et qu'aucune autre session ngrok n'est active."
                )
                logger.warning(self._status.error)
                await self._terminate()
                self._publish()
                return self._status

            self._status.running = True
            self._status.public_url = url
            self._status.managed_by_bridge = True
            self._status.error = None
            logger.info("Tunnel ngrok actif : %s", url)
            self._publish()
            return self._status

    def _build_command(self, binary: str, settings: Settings) -> list[str]:
        command = [binary, "http", str(settings.bridge_port), "--log=stdout"]
        if settings.ngrok_domain:
            domain = settings.ngrok_domain.replace("https://", "").replace("http://", "").strip("/")
            command.append(f"--domain={domain}")

        # ngrok n'utilise QUE les fichiers passes en --config : si le Bridge
        # fournit le sien, il doit aussi rappeler celui de l'utilisateur, sinon
        # l'authtoken deja enregistre par la commande ngrok serait perdu.
        config_file = settings.data_dir / "ngrok.yml"
        if config_file.exists():
            for path in (default_config_path(), config_file):
                if path is not None and path.exists():
                    command.extend(["--config", str(path)])
        return command

    async def _configure_token(self, binary: str, token: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                binary,
                "config",
                "add-authtoken",
                token,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=15)
        except (OSError, TimeoutError) as exc:
            logger.warning("Configuration du token ngrok impossible : %s", exc)

    async def _wait_for_url(self) -> str | None:
        deadline = asyncio.get_event_loop().time() + STARTUP_TIMEOUT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                return None  # le processus s'est arrete tout seul
            url = await read_public_url()
            if url:
                return url
            await asyncio.sleep(1.0)
        return None

    async def _terminate(self) -> None:
        """Arrete le processus ngrok. A appeler avec le verrou deja detenu.

        ``asyncio.Lock`` n'est pas reentrant : si ``start()`` appelait
        directement ``stop()`` apres un echec, le Bridge resterait bloque pour
        toujours au demarrage. Les deux chemins passent donc par cette methode
        qui ne prend aucun verrou.
        """
        process = self._process
        job = self._job
        self._process = None
        self._job = None
        if process is None:
            close_job(job)
            self._status.running = False
            return
        try:
            process.terminate()
            await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=10)
        except (TimeoutError, OSError):
            with contextlib.suppress(OSError):
                process.kill()
        close_job(job)
        self._status.running = False
        self._status.public_url = None
        logger.info("Tunnel ngrok arrete")
        self._publish()

    async def stop(self) -> None:
        async with self._lock:
            await self._terminate()

    async def refresh(self) -> TunnelStatus:
        """Verifie que le tunnel est toujours joignable."""
        if not self._status.enabled:
            return self._status
        url = await read_public_url()
        self._status.running = url is not None
        self._status.public_url = url
        return self._status

    def _publish(self) -> None:
        event_bus.publish(EventType.TUNNEL_STATUS, self._status.to_dict())


ngrok_service = NgrokService()
