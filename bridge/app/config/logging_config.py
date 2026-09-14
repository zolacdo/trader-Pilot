"""Journalisation structuree avec rotation et masquage systematique des secrets."""

from __future__ import annotations

import contextlib
import json
import logging
import logging.handlers
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Motifs de secrets a masquer avant toute ecriture (fichier ou console).
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(sk-or-v1-)[A-Za-z0-9\-_]{8,}", re.IGNORECASE),
    re.compile(r"\b([0-9]{4,8}:)[A-Za-z0-9_-]{30,}\b"),  # token bot telegram
    re.compile(r"((?:api[_-]?hash|api_hash)\W{1,4})([0-9a-f]{16,})", re.IGNORECASE),
    re.compile(r"((?:password|passwd|pwd|mot_de_passe)\W{1,4})(\S+)", re.IGNORECASE),
    re.compile(
        r"((?:authtoken|auth_token|token|secret|api[_-]?key)\W{1,4})([A-Za-z0-9\-_\.]{8,})",
        re.IGNORECASE,
    ),
    re.compile(r"((?:otp|code)\W{1,4})(\d{4,8})", re.IGNORECASE),
    re.compile(r"(1[A-Za-z0-9+/=_-]{40,})"),  # string session telethon
]

_REDACTED = "***REDACTED***"

# Secrets exacts enregistres au demarrage (cles reelles chargees depuis .env).
_KNOWN_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Enregistre une valeur sensible pour qu'elle ne soit jamais journalisee."""
    if value and len(value.strip()) >= 6:
        _KNOWN_SECRETS.add(value.strip())


def redact(text: str) -> str:
    """Masque les secrets connus et les motifs sensibles dans une chaine."""
    if not text:
        return text
    cleaned = text
    for secret in _KNOWN_SECRETS:
        if secret in cleaned:
            cleaned = cleaned.replace(secret, _REDACTED)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            cleaned = pattern.sub(lambda m: f"{m.group(1)}{_REDACTED}", cleaned)
        else:
            cleaned = pattern.sub(_REDACTED, cleaned)
    return cleaned


def mask_middle(value: str | None, keep_start: int = 4, keep_end: int = 4) -> str:
    """Affichage partiel d'un secret pour l'interface (ex: sk-o...9f2a)."""
    if not value:
        return ""
    stripped = value.strip()
    if len(stripped) <= keep_start + keep_end:
        return "*" * len(stripped)
    return f"{stripped[:keep_start]}...{stripped[-keep_end:]}"


class RedactingFilter(logging.Filter):
    """Masque les secrets sans alterer le type des arguments.

    Seules les chaines sont nettoyees : convertir un nombre en texte casserait
    les formats numeriques comme ``%.1f`` ou ``%d``.
    """

    @staticmethod
    def _clean(value: object) -> object:
        return redact(value) if isinstance(value, str) else value

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {key: self._clean(value) for key, value in record.args.items()}
                else:
                    record.args = tuple(self._clean(arg) for arg in record.args)
        except Exception:  # la journalisation ne doit jamais casser l'application
            pass
        return True


class JsonFormatter(logging.Formatter):
    """Format JSON une ligne par evenement, pratique pour l'export de diagnostic."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key in ("event", "channel_id", "signal_id", "ticket", "symbol"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)-28s %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure la racine : console lisible + fichier JSON avec rotation."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    # La console Windows encode en cp1252 par defaut : un titre de canal en
    # caracteres stylises ou un emoji y fait echouer l'ecriture, et la ligne
    # est PERDUE. On force UTF-8, et on remplace ce qui resterait impossible
    # a rendre plutot que de jeter le message.
    flux = sys.stdout
    reconfigurer = getattr(flux, "reconfigure", None)
    if callable(reconfigurer):
        # Flux non reconfigurable (redirige, ferme) : on continue sans.
        with contextlib.suppress(ValueError, OSError):
            reconfigurer(encoding="utf-8", errors="replace")

    console = logging.StreamHandler(flux)
    console.setFormatter(ConsoleFormatter())
    console.addFilter(RedactingFilter())
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "bridge.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(RedactingFilter())
        root.addHandler(file_handler)

    # Bibliotheques trop bavardes
    for noisy in ("telethon", "httpx", "httpcore", "asyncio", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
