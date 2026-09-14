"""Chiffrement au repos des secrets (cle OpenRouter, api_hash Telegram, ...).

Les secrets ne transitent jamais en clair par l'API : seul un indice partiel
(``sk-o...9f2a``) est expose a l'application mobile.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import os
import secrets as pysecrets
import stat

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config.logging_config import get_logger, mask_middle, register_secret
from app.config.settings import Settings, get_settings
from app.models.core import Secret, utcnow

logger = get_logger(__name__)

# Cles de secrets connues
SECRET_OPENROUTER_API_KEY = "openrouter.api_key"
# Moteurs compatibles OpenAI : leurs cles ne figurent jamais dans les reglages
# affichables, seulement ici, chiffrees.
SECRET_GROQ_API_KEY = "groq.api_key"
SECRET_GOOGLE_API_KEY = "google.api_key"
SECRET_TELEGRAM_API_HASH = "telegram.api_hash"
SECRET_TELEGRAM_SESSION = "telegram.session"
SECRET_TELEGRAM_2FA_HINT = "telegram.2fa_hint"
SECRET_PAIRING_CODE = "pairing.code"
SECRET_MT5_PASSWORD = "mt5.password"


class MasterKeyError(RuntimeError):
    """La cle maitre est absente ou invalide."""


def load_master_key(settings: Settings | None = None) -> bytes:
    """Retourne la cle Fernet, en la creant sur disque au premier demarrage."""
    settings = settings or get_settings()
    if settings.master_key.strip():
        key = settings.master_key.strip().encode()
        try:
            Fernet(key)
        except Exception as exc:  # cle invalide fournie par l'utilisateur
            raise MasterKeyError(
                "MASTER_KEY invalide : generer avec "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from exc
        register_secret(key.decode())
        return key

    key_file = settings.master_key_file
    if key_file.exists():
        key = key_file.read_bytes().strip()
        try:
            Fernet(key)
        except Exception as exc:
            raise MasterKeyError(f"Fichier de cle corrompu : {key_file}") from exc
        register_secret(key.decode())
        return key

    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    # Les systemes de fichiers sans permissions POSIX ignorent simplement l'appel.
    with contextlib.suppress(OSError):
        key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    register_secret(key.decode())
    logger.warning("Nouvelle cle maitre generee dans %s - sauvegardez ce fichier", key_file)
    return key


class SecretStore:
    """Lecture/ecriture des secrets chiffres en base."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._fernet = Fernet(load_master_key(self._settings))

    async def set(self, key: str, value: str | None) -> None:
        if value is None or not value.strip():
            await self.delete(key)
            return
        clean = value.strip()
        register_secret(clean)
        ciphertext = self._fernet.encrypt(clean.encode()).decode()
        existing = await self._session.get(Secret, key)
        if existing is None:
            self._session.add(
                Secret(key=key, ciphertext=ciphertext, hint=mask_middle(clean), updated_at=utcnow())
            )
        else:
            existing.ciphertext = ciphertext
            existing.hint = mask_middle(clean)
            existing.updated_at = utcnow()
            self._session.add(existing)
        await self._session.flush()

    async def get(self, key: str) -> str | None:
        record = await self._session.get(Secret, key)
        if record is None:
            return None
        try:
            value = self._fernet.decrypt(record.ciphertext.encode()).decode()
        except InvalidToken:
            logger.error("Secret %s illisible : la cle maitre a change", key)
            return None
        register_secret(value)
        return value

    async def hint(self, key: str) -> str:
        record = await self._session.get(Secret, key)
        return record.hint if record else ""

    async def exists(self, key: str) -> bool:
        record = await self._session.get(Secret, key)
        return record is not None

    async def delete(self, key: str) -> None:
        record = await self._session.get(Secret, key)
        if record is not None:
            await self._session.delete(record)
            await self._session.flush()

    async def keys(self) -> list[str]:
        result = await self._session.exec(select(Secret.key))
        return list(result.all())


# ---------------------------------------------------------------------------
# Jetons d'appairage
# ---------------------------------------------------------------------------

def generate_pairing_code() -> str:
    """Code court lisible a saisir sur le telephone (format XXXX-XXXX)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans I, O, 0, 1
    raw = "".join(pysecrets.choice(alphabet) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def generate_device_token() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)


def normalize_pairing_code(value: str) -> str:
    """Forme canonique d'un code : majuscules, sans tiret ni espace.

    Le Bridge affiche ``XXXX-XXXX`` pour la lisibilite, mais l'utilisateur peut
    saisir le code avec ou sans tiret, et l'application mobile le transmet sous
    forme compacte. La comparaison doit donc ignorer la mise en forme.
    """
    return "".join(char for char in value.upper() if char.isalnum())


def constant_time_equals(left: str, right: str) -> bool:
    """Comparaison de codes d'appairage, insensible a la mise en forme."""
    return hmac.compare_digest(normalize_pairing_code(left), normalize_pairing_code(right))
