"""Garde-fous de securite des notifications (CDC2 section 94).

Deux regles, appliquees a chaque notification avant enregistrement :

1. aucun secret ne sort du Bridge : cles, jetons, mots de passe, identifiants
   de compte complets sont masques ou retires ;
2. aucune action financiere critique n'est declenchable depuis la notification :
   la charge utile ne contient que du descriptif et de la navigation.
"""

from __future__ import annotations

import re
from typing import Any

from app.config.logging_config import mask_middle, redact

# Clefs dont la valeur est potentiellement un secret : elles ne partent jamais.
SENSITIVE_KEY_PARTS: frozenset[str] = frozenset(
    {
        "apikey",
        "api_key",
        "auth",
        "authorization",
        "authtoken",
        "bearer",
        "credential",
        "credentials",
        "hash",
        "masterkey",
        "master_key",
        "otp",
        "pairing",
        "passphrase",
        "password",
        "passwd",
        "private",
        "pwd",
        "secret",
        "session",
        "token",
    }
)

# Clefs qui transformeraient la notification en telecommande de trading.
# Le telephone peut ouvrir un ecran, jamais envoyer un ordre depuis la banniere.
ACTIONABLE_KEY_PARTS: frozenset[str] = frozenset(
    {
        "cancelorder",
        "closeorder",
        "closeposition",
        "command",
        "confirm",
        "execute",
        "modifyorder",
        "placeorder",
        "sendorder",
    }
)

# Clefs autorisees a porter un identifiant de compte : la valeur est masquee.
ACCOUNT_KEY_PARTS: frozenset[str] = frozenset({"account", "login", "accountlogin"})

MAX_DATA_KEYS = 30
MAX_VALUE_LENGTH = 300

_LONG_DIGITS = re.compile(r"\b\d{6,}\b")


def _normalized(key: str) -> str:
    return key.replace("-", "").replace("_", "").replace(" ", "").lower()


def is_sensitive_key(key: str) -> bool:
    normalized = _normalized(key)
    return any(part.replace("_", "") in normalized for part in SENSITIVE_KEY_PARTS)


def is_actionable_key(key: str) -> bool:
    normalized = _normalized(key)
    return any(part in normalized for part in ACTIONABLE_KEY_PARTS)


def is_account_key(key: str) -> bool:
    normalized = _normalized(key)
    return any(part in normalized for part in ACCOUNT_KEY_PARTS)


def mask_account(value: Any) -> str:
    """Identifiant de compte reduit a ses derniers chiffres (ex: ***4821)."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return f"***{text[-4:]}"


def sanitize_text(value: str | None) -> str:
    """Masque les secrets connus, les motifs sensibles et les longs numeros."""
    if not value:
        return ""
    cleaned = redact(str(value))
    cleaned = _LONG_DIGITS.sub(lambda match: mask_account(match.group(0)), cleaned)
    return cleaned.strip()


def _sanitize_value(key: str, value: Any, depth: int) -> Any:
    if is_account_key(key):
        return mask_account(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return redact(value)[:MAX_VALUE_LENGTH]
    if isinstance(value, list | tuple):
        if depth >= 2:
            return []
        return [_sanitize_value(key, item, depth + 1) for item in list(value)[:20]]
    if isinstance(value, dict):
        if depth >= 2:
            return {}
        return _sanitize_mapping(value, depth + 1)
    return redact(str(value))[:MAX_VALUE_LENGTH]


def _sanitize_mapping(data: dict[str, Any], depth: int) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for raw_key, value in data.items():
        key = str(raw_key)
        if is_sensitive_key(key) or is_actionable_key(key):
            continue
        cleaned[key] = _sanitize_value(key, value, depth)
        if len(cleaned) >= MAX_DATA_KEYS:
            break
    return cleaned


def sanitize_data(data: dict[str, Any] | None) -> dict[str, Any]:
    """Charge utile purgee : ni secret, ni ordre executable, ni objet profond."""
    if not data:
        return {}
    return _sanitize_mapping(data, 0)


def sanitize_draft_fields(
    title: str, body: str, data: dict[str, Any] | None
) -> tuple[str, str, dict[str, Any]]:
    """Applique les deux regles du CDC2 section 94 a une notification complete."""
    return sanitize_text(title)[:255], sanitize_text(body), sanitize_data(data)


def partial_secret(value: str | None) -> str:
    """Affichage partiel pour le diagnostic (jamais la valeur complete)."""
    return mask_middle(value)
