"""Session utilisateur Telegram (MTProto) du Bridge TradePilot.

Ce n'est PAS un bot : la chaine de session Telethon est chiffree dans la table
``secrets`` (cle ``telegram.session``), jamais ecrite en clair sur le disque ni
journalisee. La connexion se fait en trois appels REST successifs :
``start_login`` -> ``submit_code`` -> ``submit_password`` (si 2FA).
"""

from __future__ import annotations

import asyncio
import secrets as pysecrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from app.config.logging_config import get_logger, mask_middle, register_secret
from app.config.settings import APP_VERSION, get_settings
from app.database.session import session_scope
from app.models.core import utcnow
from app.models.enums import ConnectionState
from app.models.telegram import TelegramAccount
from app.services import journal
from app.services.events import EventType, event_bus
from app.services.security.crypto import SECRET_TELEGRAM_API_HASH, SECRET_TELEGRAM_SESSION, SecretStore

logger = get_logger(__name__)

ACCOUNT_ID = 1
LOGIN_TTL_SECONDS = 600
WATCHDOG_INTERVAL = 20.0
BACKOFF_STEPS = (5.0, 10.0, 20.0, 60.0)
MAX_RECONNECT_ATTEMPTS = 12
DEVICE_MODEL = "TradePilot Bridge"

# Traduction des erreurs Telethon en messages affichables, sans divulguer de secret.
_LOGIN_ERROR_MESSAGES: dict[type[Exception], str] = {
    errors.ApiIdInvalidError: "Identifiants API Telegram invalides (api_id / api_hash).",
    errors.PhoneNumberInvalidError: "Numero de telephone invalide.",
    errors.PhoneCodeInvalidError: "Code de connexion invalide.",
    errors.PhoneCodeExpiredError: "Code de connexion expire, relancez la connexion.",
    errors.PasswordHashInvalidError: "Mot de passe 2FA invalide.",
}


class TelegramServiceError(RuntimeError):
    """Erreur Telegram dont le message est directement affichable a l'utilisateur."""


class TelegramNotConnectedError(TelegramServiceError):
    """Aucune session utilisateur active."""


class TelegramLoginError(TelegramServiceError):
    """Echec d'une etape de connexion (code, mot de passe, demande expiree)."""


class TelegramFloodError(TelegramServiceError):
    """Telegram impose une temporisation (FloodWait). Le delai est expose tel quel."""

    def __init__(self, seconds: int) -> None:
        self.seconds = int(seconds)
        super().__init__(f"Limite Telegram atteinte, reessayez dans {self.seconds} secondes.")


def _user_payload(me: Any) -> dict[str, Any]:
    """Identite publique du compte connecte (aucune donnee sensible)."""
    return {"id": getattr(me, "id", None), "username": getattr(me, "username", None),
            "firstName": getattr(me, "first_name", None)}


def _user_label(me: Any) -> str:
    """Libelle non sensible pour les journaux : @pseudo ou identifiant numerique."""
    username = getattr(me, "username", None)
    return f"@{username}" if username else f"id {getattr(me, 'id', 0)}"


def _translate(exc: Exception, fallback: str) -> TelegramServiceError:
    """Erreur Telethon -> erreur metier francaise (aucun secret journalise)."""
    if isinstance(exc, errors.FloodWaitError):
        return TelegramFloodError(exc.seconds)
    message = _LOGIN_ERROR_MESSAGES.get(type(exc))
    if message is None:
        logger.error("Erreur Telegram : %s", type(exc).__name__)
        message = fallback
    return TelegramLoginError(message)


@dataclass(slots=True)
class _PendingLogin:
    """Demande de connexion en cours : vit UNIQUEMENT en memoire, jamais en base."""

    request_id: str
    client: TelegramClient
    api_id: int
    api_hash: str
    phone: str
    phone_code_hash: str
    created_at: datetime = field(default_factory=utcnow)

    @property
    def expired(self) -> bool:
        return utcnow() - self.created_at > timedelta(seconds=LOGIN_TTL_SECONDS)


class TelegramService:
    """Cycle de vie complet de la session utilisateur Telegram."""

    def __init__(self) -> None:
        self._client: TelegramClient | None = None
        self._pending: dict[str, _PendingLogin] = {}
        self._state: ConnectionState = ConnectionState.NOT_CONFIGURED
        self._last_error: str | None = None
        self._username: str | None = None
        self._phone: str | None = None
        self._authorized = False
        self._stopping = False
        self._lock = asyncio.Lock()
        self._watchdog: asyncio.Task[None] | None = None

    @property
    def client(self) -> TelegramClient | None:
        return self._client

    @property
    def connected(self) -> bool:
        return bool(self._client is not None and self._authorized and self._client.is_connected())

    def require_client(self) -> TelegramClient:
        """Retourne le client actif, sinon leve une erreur explicite."""
        if self._client is None or not self._authorized:
            raise TelegramNotConnectedError("Compte Telegram non connecte.")
        return self._client

    async def start_login(self, api_id: int, api_hash: str, phone: str) -> dict[str, Any]:
        """Etape 1 : envoi du code par Telegram. Retourne un identifiant opaque."""
        clean_hash = (api_hash or "").strip()
        clean_phone = (phone or "").strip()
        register_secret(clean_hash)
        if not clean_hash or not clean_phone:
            raise TelegramLoginError("api_id, api_hash et numero de telephone sont obligatoires.")
        self._purge_expired()

        client = self._build_client(int(api_id), clean_hash)
        try:
            await client.connect()
            sent = await client.send_code_request(clean_phone)
        except Exception as exc:
            await self._safe_disconnect(client)
            raise _translate(exc, "Impossible d'envoyer le code de connexion Telegram.") from exc

        request_id = pysecrets.token_urlsafe(16)
        # Le vrai phone_code_hash ne quitte jamais le Bridge : seul l'identifiant opaque circule.
        self._pending[request_id] = _PendingLogin(
            request_id, client, int(api_id), clean_hash, clean_phone, sent.phone_code_hash
        )
        self._set_state(ConnectionState.CONNECTING)
        logger.info("Code de connexion Telegram envoye au %s", mask_middle(clean_phone, 4, 2))
        return {"status": "code_sent", "phoneCodeHash": request_id, "expiresIn": LOGIN_TTL_SECONDS}

    async def submit_code(self, request_id: str, code: str) -> dict[str, Any]:
        """Etape 2 : validation du code recu par SMS ou dans l'application Telegram."""
        register_secret(code)
        pending = self._get_pending(request_id)
        try:
            await pending.client.sign_in(
                pending.phone, (code or "").strip(), phone_code_hash=pending.phone_code_hash
            )
        except errors.SessionPasswordNeededError:
            # 2FA active : la demande reste valide pour l'appel a submit_password.
            return {"status": "password_required"}
        except Exception as exc:
            if isinstance(exc, errors.PhoneCodeExpiredError):
                await self._safe_disconnect(self._pending.pop(request_id, pending).client)
            raise _translate(exc, "Echec de la validation du code.") from exc
        return await self._finalize_login(pending)

    async def submit_password(self, request_id: str, password: str) -> dict[str, Any]:
        """Etape 3 : mot de passe de la verification en deux etapes (2FA)."""
        register_secret(password)
        pending = self._get_pending(request_id)
        try:
            await pending.client.sign_in(password=password or "")
        except Exception as exc:
            raise _translate(exc, "Echec de la validation du mot de passe 2FA.") from exc
        return await self._finalize_login(pending)

    async def _finalize_login(self, pending: _PendingLogin) -> dict[str, Any]:
        """Sauvegarde chiffree de la session puis activation du client."""
        client = pending.client
        me = await client.get_me()
        session_string = client.session.save()
        register_secret(session_string)
        await self._store_credentials(pending, session_string, me)
        self._pending.pop(pending.request_id, None)
        await self._activate_client(client, phone=pending.phone, me=me)
        message = f"Compte Telegram connecte : {_user_label(me)}"
        await journal.log("telegram_connected", message, category="telegram")
        return {"status": "connected", "user": _user_payload(me)}

    async def connect_existing(self) -> bool:
        """Recharge la session chiffree et se reconnecte silencieusement."""
        async with self._lock:
            if self.connected:
                return True
            creds = await self._load_credentials()
            if creds is None:
                self._set_state(ConnectionState.NOT_CONFIGURED)
                return False
            api_id, api_hash, session_string, phone = creds
            client = self._build_client(api_id, api_hash, session_string)
            self._set_state(ConnectionState.CONNECTING)
            try:
                await client.connect()
                authorized = await client.is_user_authorized()
            except Exception as exc:
                await self._safe_disconnect(client)
                logger.warning("Reconnexion Telegram impossible : %s", type(exc).__name__)
                return self._fail("Connexion Telegram impossible.", ConnectionState.ERROR)
            if not authorized:
                await self._safe_disconnect(client)
                self._authorized = False
                message = "Session Telegram expiree, reconnexion requise."
                return self._fail(message, ConnectionState.DISCONNECTED)
            me = await client.get_me()
            await self._activate_client(client, phone=phone, me=me)
            logger.info("Session Telegram restauree pour %s", _user_label(me))
            return True

    def _fail(self, message: str, state: ConnectionState) -> bool:
        """Memorise la derniere erreur, publie l'etat et retourne False."""
        self._last_error = message
        self._set_state(state)
        return False

    async def disconnect(self) -> None:
        """Ferme le client sans supprimer la session stockee."""
        self._stopping = True
        await self._cancel_watchdog()
        client, self._client = self._client, None
        self._authorized = False
        await self._safe_disconnect(client)
        for pending in list(self._pending.values()):
            await self._safe_disconnect(pending.client)
        self._pending.clear()
        self._set_state(ConnectionState.DISCONNECTED)

    async def logout(self) -> None:
        """Deconnexion definitive : la session chiffree stockee est supprimee."""
        if self._client is not None:
            try:
                await self._client.log_out()
            except Exception as exc:  # la session locale est supprimee dans tous les cas
                logger.warning("Deconnexion Telegram distante impossible : %s", type(exc).__name__)
        await self.disconnect()
        try:
            async with session_scope() as session:
                await SecretStore(session).delete(SECRET_TELEGRAM_SESSION)
                account = await session.get(TelegramAccount, ACCOUNT_ID)
                if account is not None:
                    account.authorized, account.updated_at = False, utcnow()
                    session.add(account)
        except Exception:
            logger.warning("Suppression de la session Telegram stockee impossible")
        self._username = self._phone = None
        self._set_state(ConnectionState.NOT_CONFIGURED)
        await journal.log("telegram_logout", "Session Telegram supprimee", category="telegram")

    async def status(self) -> dict[str, Any]:
        """Etat courant, sans jamais exposer de secret (telephone masque)."""
        snapshot = await self._account_snapshot()
        authorized = self._authorized or bool(snapshot.get("authorized"))
        payload = self._state_payload()
        if self._state is ConnectionState.NOT_CONFIGURED and authorized:
            payload["state"] = ConnectionState.DISCONNECTED.value
        payload["authorized"] = authorized
        payload["username"] = self._username or snapshot.get("username")
        payload["phone"] = mask_middle(self._phone or snapshot.get("phone"), 4, 2)
        return payload

    def _build_client(self, api_id: int, api_hash: str, session: str | None = None) -> TelegramClient:
        register_secret(api_hash)
        register_secret(session)
        return TelegramClient(
            StringSession(session or None), api_id, api_hash, device_model=DEVICE_MODEL,
            system_version="Windows", app_version=APP_VERSION, connection_retries=3,
            retry_delay=5, auto_reconnect=True,
        )

    def _get_pending(self, request_id: str) -> _PendingLogin:
        self._purge_expired()
        pending = self._pending.get(request_id)
        if pending is None:
            raise TelegramLoginError("Demande de connexion inconnue ou expiree, relancez la connexion.")
        return pending

    def _purge_expired(self) -> None:
        """Oublie les demandes de plus de 10 minutes (aucun secret ne survit)."""
        for request_id, pending in list(self._pending.items()):
            if pending.expired:
                self._pending.pop(request_id, None)
                asyncio.ensure_future(self._safe_disconnect(pending.client))  # noqa: RUF006

    async def _safe_disconnect(self, client: TelegramClient | None) -> None:
        if client is None:
            return
        try:
            result = client.disconnect()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.debug("Deconnexion du client Telegram ignoree")

    async def _activate_client(self, client: TelegramClient, phone: str | None, me: Any) -> None:
        previous = self._client
        if previous is not None and previous is not client:
            await self._safe_disconnect(previous)
        self._client = client
        self._authorized = True
        self._stopping = False
        self._last_error = None
        self._phone = phone or getattr(me, "phone", None)
        self._username = getattr(me, "username", None)
        self._set_state(ConnectionState.CONNECTED)
        self._start_watchdog()

    async def _store_credentials(self, pending: _PendingLogin, session_string: str, me: Any) -> None:
        async with session_scope() as session:
            store = SecretStore(session)
            await store.set(SECRET_TELEGRAM_API_HASH, pending.api_hash)
            await store.set(SECRET_TELEGRAM_SESSION, session_string)
            account = await session.get(TelegramAccount, ACCOUNT_ID) or TelegramAccount(id=ACCOUNT_ID)
            account.api_id, account.phone = pending.api_id, pending.phone
            account.user_id = getattr(me, "id", None)
            account.username = getattr(me, "username", None)
            account.first_name = getattr(me, "first_name", None)
            account.authorized, account.last_error = True, None
            account.last_connected_at = account.updated_at = utcnow()
            session.add(account)

    async def _load_credentials(self) -> tuple[int, str, str, str | None] | None:
        """api_id / api_hash / session depuis la base, avec repli sur le fichier .env."""
        settings = get_settings()
        try:
            async with session_scope() as session:
                store = SecretStore(session)
                stored = await store.get(SECRET_TELEGRAM_SESSION)
                api_hash = await store.get(SECRET_TELEGRAM_API_HASH) or settings.telegram_api_hash.strip()
                account = await session.get(TelegramAccount, ACCOUNT_ID)
        except Exception:
            logger.debug("Aucune session Telegram lisible en base")
            return None
        raw_id = settings.telegram_api_id.strip()
        api_id = (account.api_id if account else None) or (int(raw_id) if raw_id.isdigit() else None)
        if not stored or not api_hash or not api_id:
            return None
        register_secret(api_hash)
        register_secret(stored)
        phone = (account.phone if account else None) or settings.telegram_phone.strip() or None
        return int(api_id), api_hash, stored, phone

    async def _account_snapshot(self) -> dict[str, Any]:
        """Lecture tolerante du compte : dictionnaire vide si la base n'est pas prete."""
        try:
            async with session_scope() as session:
                account = await session.get(TelegramAccount, ACCOUNT_ID)
                if account is None:
                    return {}
                return {"authorized": account.authorized, "username": account.username,
                        "phone": account.phone}
        except Exception:
            return {}

    def _set_state(self, state: ConnectionState) -> None:
        self._state = state
        event_bus.publish(EventType.TELEGRAM_STATUS, self._state_payload())

    def _state_payload(self) -> dict[str, Any]:
        return {"state": self._state.value, "username": self._username,
                "phone": mask_middle(self._phone, 4, 2), "authorized": self._authorized,
                "lastError": self._last_error}

    def _start_watchdog(self) -> None:
        if self._watchdog is None or self._watchdog.done():
            self._watchdog = asyncio.create_task(self._supervise())

    async def _cancel_watchdog(self) -> None:
        task, self._watchdog = self._watchdog, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # l'arret ne doit jamais echouer
                logger.debug("Watchdog Telegram arrete")

    async def _supervise(self) -> None:
        """Backoff 5s, 10s, 20s puis 60s au maximum, abandon apres N tentatives."""
        attempt = 0
        try:
            while not self._stopping:
                await asyncio.sleep(WATCHDOG_INTERVAL)
                client = self._client
                if client is None or self._stopping:
                    break
                if client.is_connected():
                    attempt = 0
                    if self._state is not ConnectionState.CONNECTED:
                        self._set_state(ConnectionState.CONNECTED)
                    continue
                attempt += 1
                if attempt > MAX_RECONNECT_ATTEMPTS:
                    self._last_error = "Reconnexion Telegram abandonnee apres plusieurs tentatives."
                    logger.error("Reconnexion Telegram abandonnee")
                    self._set_state(ConnectionState.ERROR)
                    break
                delay = BACKOFF_STEPS[min(attempt - 1, len(BACKOFF_STEPS) - 1)]
                self._set_state(ConnectionState.CONNECTING)
                logger.warning("Connexion Telegram perdue, nouvelle tentative dans %.0f s", delay)
                await asyncio.sleep(delay)
                try:
                    await client.connect()
                    if await client.is_user_authorized():
                        attempt = 0
                        self._last_error = None
                        self._set_state(ConnectionState.CONNECTED)
                        logger.info("Connexion Telegram retablie")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Echec de reconnexion Telegram : %s", type(exc).__name__)
        except asyncio.CancelledError:  # arret normal du Bridge
            pass
