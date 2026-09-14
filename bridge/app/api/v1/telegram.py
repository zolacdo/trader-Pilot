"""Routes Telegram : connexion du compte utilisateur et decouverte de canaux."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger, register_secret
from app.config.settings import get_settings
from app.database.session import get_session
from app.models.core import Device
from app.models.enums import EventLevel
from app.schemas.requests import (
    ChannelSearchRequest,
    TelegramCodeRequest,
    TelegramLoginStartRequest,
    TelegramPasswordRequest,
)
from app.services import journal, telegram_runtime
from app.services.security.auth import require_device
from app.services.telegram import (
    TelegramFloodError,
    TelegramLoginError,
    TelegramNotConnectedError,
    TelegramServiceError,
    resolve_channel,
    search_channels,
    telegram_service,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


def _handle_error(exc: Exception) -> HTTPException:
    """Traduit les erreurs Telethon en messages comprehensibles (CDC section 62)."""
    if isinstance(exc, TelegramFloodError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, TelegramNotConnectedError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, TelegramLoginError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, TelegramServiceError):
        return HTTPException(status_code=502, detail=str(exc))
    logger.exception("Erreur Telegram inattendue")
    return HTTPException(status_code=500, detail="Erreur Telegram inattendue")


@router.get("/status")
async def telegram_status(_: Device = Depends(require_device)) -> dict[str, Any]:
    status = await telegram_service.status()
    settings = get_settings()
    raw_id = settings.telegram_api_id.strip()
    # Valeurs deja presentes dans le .env du Bridge : l'application peut les
    # pre-remplir. L'api_hash reste secret, on signale seulement sa presence.
    status["envDefaults"] = {
        "apiId": int(raw_id) if raw_id.isdigit() else None,
        "phone": settings.telegram_phone.strip() or None,
        "apiHashAvailable": bool(settings.telegram_api_hash.strip()),
    }
    return status


@router.post("/login/start")
async def login_start(
    payload: TelegramLoginStartRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Envoie le code de connexion. L'api_hash n'est jamais journalise.

    Ce qui n'est pas fourni par l'application est repris du fichier .env du
    Bridge : l'utilisateur qui a deja renseigne ses identifiants sur
    l'ordinateur n'a pas a les retaper sur le telephone.
    """
    settings = get_settings()
    raw_id = settings.telegram_api_id.strip()
    api_id = payload.api_id or (int(raw_id) if raw_id.isdigit() else None)
    api_hash = payload.api_hash or settings.telegram_api_hash.strip() or None
    phone = payload.phone or settings.telegram_phone.strip() or None

    missing = [
        label
        for label, value in (("apiId", api_id), ("apiHash", api_hash), ("phone", phone))
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                "Identifiants Telegram incomplets : "
                + ", ".join(missing)
                + ". Renseignez-les dans l'application, ou dans bridge/.env "
                "(TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE)."
            ),
        )

    register_secret(api_hash)
    try:
        result = await telegram_service.start_login(api_id, api_hash, phone)
    except Exception as exc:
        raise _handle_error(exc) from exc
    await journal.record(
        session,
        event="telegram_login_started",
        message="Code de connexion Telegram demande",
        category="telegram",
    )
    return result


async def _suivre_la_connexion(session: AsyncSession, connecte: bool) -> None:
    """Aligne l'ecoute des canaux sur l'etat reel de la connexion.

    Sans cela, l'ecoute ne demarrait qu'au lancement du Bridge : se connecter
    depuis l'application ne recevait aucun message jusqu'au redemarrage.
    """
    if connecte:
        listener = await telegram_runtime.start_listener()
        if listener is None:
            await journal.record(
                session,
                event="telegram_listener_failed",
                message=(
                    "Compte connecte, mais l'ecoute des canaux n'a pas demarre. "
                    "Aucun message ne sera recu tant qu'elle reste arretee."
                ),
                category="telegram",
                level=EventLevel.WARNING,
            )
        return
    await telegram_runtime.stop_listener()


@router.post("/login/code")
async def login_code(
    payload: TelegramCodeRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    register_secret(payload.code)
    try:
        result = await telegram_service.submit_code(payload.request_id, payload.code)
    except Exception as exc:
        raise _handle_error(exc) from exc
    if result.get("status") == "connected":
        await journal.record(
            session,
            event="telegram_connected",
            message="Compte Telegram connecte",
            category="telegram",
        )
        await _suivre_la_connexion(session, True)
    return result


@router.post("/login/2fa")
async def login_password(
    payload: TelegramPasswordRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    register_secret(payload.password)
    try:
        result = await telegram_service.submit_password(payload.request_id, payload.password)
    except Exception as exc:
        raise _handle_error(exc) from exc
    if result.get("status") == "connected":
        await journal.record(
            session,
            event="telegram_connected",
            message="Compte Telegram connecte (2FA)",
            category="telegram",
        )
        await _suivre_la_connexion(session, True)
    return result


@router.post("/reconnect")
async def reconnect(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    try:
        connected = await telegram_service.connect_existing()
    except Exception as exc:
        raise _handle_error(exc) from exc
    await journal.record(
        session,
        event="telegram_reconnect",
        message="Reconnexion Telegram demandee" + ("" if connected else " (aucune session)"),
        category="telegram",
    )
    await _suivre_la_connexion(session, connected)
    return await telegram_service.status()


@router.post("/disconnect")
async def disconnect(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    # L'ecoute s'arrete AVANT la deconnexion : sinon elle continuerait de
    # tourner contre un client ferme.
    await _suivre_la_connexion(session, False)
    await telegram_service.disconnect()
    await journal.record(
        session, event="telegram_disconnected", message="Telegram deconnecte", category="telegram"
    )
    return await telegram_service.status()


@router.post("/logout")
async def logout(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Deconnexion definitive : la session chiffree est supprimee."""
    await _suivre_la_connexion(session, False)
    try:
        await telegram_service.logout()
    except Exception as exc:
        raise _handle_error(exc) from exc
    await journal.record(
        session,
        event="telegram_logout",
        message="Session Telegram supprimee",
        category="telegram",
    )
    return await telegram_service.status()


# ---------------------------------------------------------------------------
# Decouverte de canaux
# ---------------------------------------------------------------------------

SUGGESTED_QUERIES = [
    "gold signals",
    "XAUUSD",
    "forex signals",
    "forex trading",
    "gold trading",
    "scalping gold",
    "EURUSD signals",
    "GBPUSD signals",
    "NASDAQ signals",
    "indices signals",
]


@router.get("/discover/suggestions")
async def discovery_suggestions(_: Device = Depends(require_device)) -> dict[str, Any]:
    return {"suggestions": SUGGESTED_QUERIES}


@router.post("/discover")
async def discover_channels(
    payload: ChannelSearchRequest, _: Device = Depends(require_device)
) -> dict[str, Any]:
    """Recherche de canaux publics. Aucun canal n'est jamais rejoint ici."""
    try:
        results = await search_channels(telegram_service, payload.query, payload.limit)
    except Exception as exc:
        raise _handle_error(exc) from exc
    return {"query": payload.query, "count": len(results), "results": results}


@router.get("/resolve")
async def resolve(
    reference: str = Query(min_length=1, max_length=128),
    _: Device = Depends(require_device),
) -> dict[str, Any]:
    """Resout @nom, un lien t.me ou un identifiant numerique."""
    try:
        result = await resolve_channel(telegram_service, reference)
    except Exception as exc:
        raise _handle_error(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Canal introuvable ou inaccessible")
    return result
