"""Transport push Firebase Cloud Messaging, API HTTP v1 (CDC2 section 50).

Le Bridge envoie, Flutter recoit. L'authentification utilise un compte de
service Google : le Bridge signe lui-meme une assertion JWT RS256 avec la cle
privee du compte, l'echange contre un jeton d'acces d'une heure, puis appelle
``/v1/projects/<projet>/messages:send``.

Aucune cle n'est ecrite en dur ni journalisee : le fichier de compte de service
vit dans ``bridge/data/`` (ignore par Git) et sa cle privee est enregistree
aupres du masqueur de secrets des le chargement.

Si rien n'est configure, le transport se declare simplement indisponible : le
reste du systeme continue avec le repli WebSocket + inbox interne.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.config.logging_config import get_logger, register_secret
from app.config.settings import get_settings

logger = get_logger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
JWT_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"

DEFAULT_TIMEOUT = 15.0
TOKEN_LIFETIME_SECONDS = 3600
TOKEN_REFRESH_MARGIN = 120.0

ANDROID_CHANNEL_ID = "tradepilot_alerts"
DEFAULT_SERVICE_ACCOUNT_FILENAME = "fcm-service-account.json"

# Variables d'environnement lues (documentees dans docs/FCM_SETUP.md).
ENV_ENABLED = "FCM_ENABLED"
ENV_FILE = "FCM_SERVICE_ACCOUNT_FILE"
ENV_INLINE = "FCM_SERVICE_ACCOUNT_JSON"
ENV_PROJECT = "FCM_PROJECT_ID"


@dataclass(frozen=True, slots=True)
class FcmCredentials:
    """Compte de service Google, sans aucune valeur affichable telle quelle."""

    project_id: str
    client_email: str
    private_key: str
    token_uri: str = DEFAULT_TOKEN_URI
    origin: str = "fichier"


@dataclass(slots=True)
class FcmSendResult:
    """Resultat d'un envoi vers un ou plusieurs appareils."""

    sent: int = 0
    failed: int = 0
    invalid_tokens: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def delivered(self) -> bool:
        return self.sent > 0


class FcmConfigurationError(RuntimeError):
    """Configuration presente mais inutilisable."""


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def default_service_account_path() -> Path:
    return get_settings().data_dir / DEFAULT_SERVICE_ACCOUNT_FILENAME


def _parse_service_account(payload: dict[str, Any], origin: str) -> FcmCredentials:
    project_id = str(os.getenv(ENV_PROJECT) or payload.get("project_id") or "").strip()
    client_email = str(payload.get("client_email") or "").strip()
    private_key = str(payload.get("private_key") or "")
    missing = [
        name
        for name, value in (
            ("project_id", project_id),
            ("client_email", client_email),
            ("private_key", private_key),
        )
        if not value
    ]
    if missing:
        raise FcmConfigurationError(f"Compte de service incomplet : {', '.join(missing)}")
    register_secret(private_key)
    return FcmCredentials(
        project_id=project_id,
        client_email=client_email,
        private_key=private_key,
        token_uri=str(payload.get("token_uri") or DEFAULT_TOKEN_URI),
        origin=origin,
    )


def load_credentials() -> tuple[FcmCredentials | None, str | None]:
    """Charge le compte de service. Renvoie (identifiants, raison d'echec)."""
    if not _env_flag(ENV_ENABLED, True):
        return None, f"{ENV_ENABLED} est a false : push distant volontairement desactive."

    inline = (os.getenv(ENV_INLINE) or "").strip()
    if inline:
        try:
            return _parse_service_account(json.loads(inline), "variable d'environnement"), None
        except (json.JSONDecodeError, FcmConfigurationError) as exc:
            return None, f"{ENV_INLINE} illisible : {exc}"

    configured_path = (os.getenv(ENV_FILE) or "").strip()
    path = Path(configured_path) if configured_path else default_service_account_path()
    if not path.is_file():
        return None, f"Fichier de compte de service introuvable : {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Fichier de compte de service illisible : {exc}"
    try:
        return _parse_service_account(payload, f"fichier {path.name}"), None
    except FcmConfigurationError as exc:
        return None, str(exc)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def build_assertion(credentials: FcmCredentials, *, now: float | None = None) -> str:
    """Assertion JWT RS256 signee avec la cle privee du compte de service."""
    issued_at = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": credentials.client_email,
        "scope": FCM_SCOPE,
        "aud": credentials.token_uri,
        "iat": issued_at,
        "exp": issued_at + TOKEN_LIFETIME_SECONDS,
    }
    segments = [
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    key = serialization.load_pem_private_key(
        credentials.private_key.encode("utf-8"), password=None
    )
    if not isinstance(key, rsa.RSAPrivateKey):  # pragma: no cover - cle non conforme
        raise FcmConfigurationError("La cle privee du compte de service n'est pas une cle RSA.")
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode('ascii')}.{_b64url(signature)}"


def build_message(
    token: str,
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    high_priority: bool = True,
    collapse_key: str | None = None,
) -> dict[str, Any]:
    """Corps JSON de l'API HTTP v1. Les valeurs de ``data`` sont des chaines."""
    payload: dict[str, Any] = {
        "token": token,
        "notification": {"title": title, "body": body},
        "android": {
            "priority": "HIGH" if high_priority else "NORMAL",
            "notification": {
                "channel_id": ANDROID_CHANNEL_ID,
                "sound": "default",
                "default_vibrate_timings": True,
            },
        },
    }
    if collapse_key:
        payload["android"]["collapse_key"] = collapse_key
    cleaned = {str(key): str(value) for key, value in (data or {}).items() if value is not None}
    if cleaned:
        payload["data"] = cleaned
    return {"message": payload}


def _new_client(timeout: float) -> httpx.AsyncClient:
    """Point d'injection unique : les tests remplacent cette fabrique."""
    return httpx.AsyncClient(timeout=timeout)


class FcmTransport:
    """Envoi push FCM. Ne leve jamais : il renvoie un resultat explicite."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self._credentials: FcmCredentials | None = None
        self._reason: str | None = None
        self._loaded = False
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self.last_error: str | None = None

    # -- configuration ----------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._credentials, self._reason = load_credentials()
            self._loaded = True

    def reload(self) -> None:
        """Relit l'environnement (apres modification du .env ou dans les tests)."""
        self._loaded = False
        self._access_token = None
        self._expires_at = 0.0
        self.last_error = None
        self._ensure_loaded()

    @property
    def configured(self) -> bool:
        self._ensure_loaded()
        return self._credentials is not None

    @property
    def credentials(self) -> FcmCredentials | None:
        self._ensure_loaded()
        return self._credentials

    @property
    def unavailable_reason(self) -> str | None:
        self._ensure_loaded()
        return self._reason

    def status(self) -> dict[str, Any]:
        """Diagnostic honnete, sans le moindre fragment de cle."""
        self._ensure_loaded()
        credentials = self._credentials
        return {
            "configured": credentials is not None,
            "transport": "FCM HTTP v1",
            "projectId": credentials.project_id if credentials else None,
            "serviceAccount": credentials.client_email if credentials else None,
            "origin": credentials.origin if credentials else None,
            "reason": self._reason,
            "lastError": self.last_error,
            "expectedFile": str(default_service_account_path()),
            "fallback": "WebSocket + notifications locales + inbox interne",
        }

    # -- jeton d'acces ----------------------------------------------------

    async def _fetch_access_token(self) -> str | None:
        credentials = self.credentials
        if credentials is None:
            return None
        now = time.time()
        if self._access_token and now < self._expires_at - TOKEN_REFRESH_MARGIN:
            return self._access_token
        try:
            assertion = build_assertion(credentials, now=now)
        except Exception as exc:  # cle illisible : on le dit, on ne plante pas
            self.last_error = f"Signature JWT impossible : {type(exc).__name__}"
            logger.error("Compte de service FCM inutilisable : %s", type(exc).__name__)
            return None
        try:
            async with _new_client(self.timeout) as client:
                response = await client.post(
                    credentials.token_uri,
                    data={"grant_type": JWT_GRANT_TYPE, "assertion": assertion},
                )
        except httpx.HTTPError as exc:
            self.last_error = f"OAuth Google injoignable : {type(exc).__name__}"
            return None
        if response.status_code >= 400:
            self.last_error = f"OAuth Google a refuse le compte de service (HTTP {response.status_code})"
            return None
        try:
            payload = response.json()
        except ValueError:
            self.last_error = "Reponse OAuth illisible"
            return None
        token = str(payload.get("access_token") or "")
        if not token:
            self.last_error = "Aucun jeton d'acces renvoye par Google"
            return None
        register_secret(token)
        self._access_token = token
        self._expires_at = now + float(payload.get("expires_in") or TOKEN_LIFETIME_SECONDS)
        self.last_error = None
        return token

    # -- envoi ------------------------------------------------------------

    async def send(
        self,
        tokens: list[str],
        *,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        high_priority: bool = True,
        collapse_key: str | None = None,
    ) -> FcmSendResult:
        """Envoie la meme notification a chaque appareil appaire."""
        credentials = self.credentials
        if credentials is None:
            return FcmSendResult(error=self._reason or "FCM non configure")
        targets = [token for token in tokens if token and token.strip()]
        if not targets:
            return FcmSendResult(error="Aucun appareil n'a enregistre de jeton push")

        access_token = await self._fetch_access_token()
        if not access_token:
            return FcmSendResult(error=self.last_error or "Jeton d'acces FCM indisponible")

        url = FCM_ENDPOINT.format(project_id=credentials.project_id)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        result = FcmSendResult()
        async with _new_client(self.timeout) as client:
            for token in targets:
                message = build_message(
                    token,
                    title=title,
                    body=body,
                    data=data,
                    high_priority=high_priority,
                    collapse_key=collapse_key,
                )
                await self._send_one(client, url, headers, token, message, result)
        if result.failed and not result.sent:
            self.last_error = result.error
        return result

    async def _send_one(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        token: str,
        message: dict[str, Any],
        result: FcmSendResult,
    ) -> None:
        try:
            response = await client.post(url, headers=headers, json=message)
        except httpx.HTTPError as exc:
            result.failed += 1
            result.error = f"FCM injoignable : {type(exc).__name__}"
            return
        if response.status_code < 300:
            result.sent += 1
            return
        result.failed += 1
        detail = _error_status(response)
        result.error = f"FCM HTTP {response.status_code} ({detail})"
        if response.status_code == 404 or detail in {"UNREGISTERED", "NOT_FOUND", "INVALID_ARGUMENT"}:
            result.invalid_tokens.append(token)


def _error_status(response: httpx.Response) -> str:
    """Extrait le code d'erreur Google sans recopier le message complet."""
    try:
        payload = response.json()
    except ValueError:
        return "reponse illisible"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        details = error.get("details")
        if isinstance(details, list):
            for item in details:
                if isinstance(item, dict) and item.get("errorCode"):
                    return str(item["errorCode"])
        return str(error.get("status") or error.get("code") or "erreur")
    return "erreur"


fcm_transport = FcmTransport()
