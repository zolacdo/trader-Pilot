"""Appairage telephone/Bridge et authentification des routes sensibles.

Aucune route de trading n'est accessible sans jeton de peripherique valide
(CDC section 41). Le jeton est remis une seule fois, apres saisie du code
d'appairage affiche par le Bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config.logging_config import get_logger, register_secret
from app.config.settings import get_settings
from app.database.session import get_session
from app.models.core import Device, utcnow
from app.services.security.crypto import (
    constant_time_equals,
    generate_device_token,
    generate_pairing_code,
    hash_token,
)

logger = get_logger(__name__)

PAIRING_TTL_MINUTES = 15


@dataclass
class PairingCode:
    code: str
    expires_at: datetime

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    @property
    def seconds_remaining(self) -> int:
        delta = self.expires_at - datetime.now(UTC)
        return max(0, int(delta.total_seconds()))


class PairingManager:
    """Detient le code d'appairage courant (memoire uniquement)."""

    def __init__(self) -> None:
        self._current: PairingCode | None = None

    def issue(self, ttl_minutes: int = PAIRING_TTL_MINUTES) -> PairingCode:
        settings = get_settings()
        code = settings.pairing_code.strip().upper() or generate_pairing_code()
        register_secret(code)
        self._current = PairingCode(
            code=code, expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        )
        return self._current

    @property
    def current(self) -> PairingCode | None:
        if self._current is not None and self._current.expired:
            return None
        return self._current

    def consume(self, submitted: str) -> bool:
        current = self.current
        if current is None:
            return False
        if constant_time_equals(submitted, current.code):
            self._current = None
            return True
        return False

    def revoke(self) -> None:
        self._current = None


pairing_manager = PairingManager()


class AuthService:
    """Creation, verification et revocation des jetons de peripherique."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_device(self, device_id: str, name: str, platform: str) -> tuple[Device, str]:
        token = generate_device_token()
        register_secret(token)
        existing = await self._session.exec(select(Device).where(Device.device_id == device_id))
        device = existing.first()
        if device is None:
            device = Device(device_id=device_id, name=name, platform=platform, token_hash=hash_token(token))
        else:
            device.name = name
            device.platform = platform
            device.token_hash = hash_token(token)
            device.revoked = False
        device.last_seen_at = utcnow()
        self._session.add(device)
        await self._session.flush()
        return device, token

    async def authenticate(self, token: str) -> Device | None:
        token_hash = hash_token(token)
        result = await self._session.exec(
            select(Device).where(Device.token_hash == token_hash, Device.revoked == False)
        )
        device = result.first()
        if device is None:
            return None
        device.last_seen_at = utcnow()
        self._session.add(device)
        return device

    async def revoke(self, device_id: str) -> bool:
        result = await self._session.exec(select(Device).where(Device.device_id == device_id))
        device = result.first()
        if device is None:
            return False
        device.revoked = True
        self._session.add(device)
        return True

    async def rotate(self, device_id: str) -> str | None:
        result = await self._session.exec(select(Device).where(Device.device_id == device_id))
        device = result.first()
        if device is None:
            return None
        token = generate_device_token()
        register_secret(token)
        device.token_hash = hash_token(token)
        device.revoked = False
        self._session.add(device)
        return token

    async def list_devices(self) -> list[Device]:
        result = await self._session.exec(select(Device).order_by(Device.created_at.desc()))
        return list(result.all())

    async def has_any_device(self) -> bool:
        result = await self._session.exec(select(Device).where(Device.revoked == False))
        return result.first() is not None


def _extract_token(authorization: str | None, header_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if header_token:
        return header_token.strip()
    return None


async def require_device(
    authorization: str | None = Header(default=None),
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
    session: AsyncSession = Depends(get_session),
) -> Device:
    """Dependance FastAPI protegeant toutes les routes sensibles."""
    token = _extract_token(authorization, x_device_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton de peripherique manquant",
            headers={"WWW-Authenticate": "Bearer"},
        )
    device = await AuthService(session).authenticate(token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton de peripherique invalide ou revoque",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return device


async def authenticate_websocket(token: str | None, session: AsyncSession) -> Device | None:
    if not token:
        return None
    return await AuthService(session).authenticate(token)


def client_is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}
