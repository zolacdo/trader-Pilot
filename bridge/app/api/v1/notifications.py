"""Routes des notifications (CDC2 sections 51, 64, 66, 67 et 90).

Inbox paginee et filtrable, marquage lu, preferences par categorie, envoi
d'essai et diagnostic du transport push. Aucune de ces routes ne declenche
d'ordre : conformement au CDC2 section 94, une notification informe, elle
n'execute jamais.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.core import Device
from app.models.intelligence import (
    NotificationCategory,
    NotificationPreference,
    NotificationPriority,
)
from app.repositories import notification_repo
from app.services import journal
from app.services.notifications.relevance import parse_hhmm
from app.services.notifications.service import event_payload, notification_service
from app.services.security.auth import require_device

router = APIRouter(prefix="/notifications", tags=["notifications"])


class PreferenceUpdate(BaseModel):
    """Reglages d'une categorie. Seuls les champs fournis sont modifies."""

    category: NotificationCategory
    enabled: bool | None = None
    push_enabled: bool | None = Field(default=None, alias="pushEnabled")
    minimum_priority: NotificationPriority | None = Field(default=None, alias="minimumPriority")
    quiet_hours_start: str | None = Field(
        default=None, alias="quietHoursStart", max_length=5
    )
    quiet_hours_end: str | None = Field(default=None, alias="quietHoursEnd", max_length=5)
    critical_bypasses_quiet_hours: bool | None = Field(
        default=None, alias="criticalBypassesQuietHours"
    )

    model_config = {"populate_by_name": True}

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def _valid_time(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return value
        if parse_hhmm(value) is None:
            raise ValueError("Heure attendue au format HH:MM")
        return value.strip()


class PreferencesRequest(BaseModel):
    """Mise a jour d'une ou plusieurs categories en un seul appel."""

    preferences: list[PreferenceUpdate] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ReadAllRequest(BaseModel):
    category: NotificationCategory | None = None


def _preference_payload(preference: NotificationPreference) -> dict[str, Any]:
    return {
        "category": preference.category.value,
        "enabled": preference.enabled,
        "pushEnabled": preference.push_enabled,
        "minimumPriority": preference.minimum_priority.value,
        "quietHoursStart": preference.quiet_hours_start,
        "quietHoursEnd": preference.quiet_hours_end,
        "criticalBypassesQuietHours": preference.critical_bypasses_quiet_hours,
        "updatedAt": preference.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Inbox (CDC2 section 67)
# ---------------------------------------------------------------------------

@router.get("")
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category: NotificationCategory | None = Query(default=None),
    priority: NotificationPriority | None = Query(default=None),
    symbol: str | None = Query(default=None, max_length=32),
    unread_only: bool = Query(default=False, alias="unreadOnly"),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Inbox paginee, filtrable par categorie, priorite ou instrument."""
    events = await notification_repo.list_events(
        session,
        limit=limit,
        offset=offset,
        category=category,
        priority=priority,
        symbol=symbol,
        unread_only=unread_only,
    )
    total = await notification_repo.count_events(
        session,
        category=category,
        priority=priority,
        symbol=symbol,
        unread_only=unread_only,
    )
    return {
        "items": [event_payload(event) for event in events],
        "total": total,
        "limit": limit,
        "offset": offset,
        "unread": await notification_repo.unread_count(session),
        "unreadByCategory": await notification_repo.unread_by_category(session),
        "categories": [item.value for item in NotificationCategory],
    }


@router.get("/unread-count")
async def unread_count(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return {
        "unread": await notification_repo.unread_count(session),
        "byCategory": await notification_repo.unread_by_category(session),
    }


@router.post("/read-all")
async def read_all(
    payload: ReadAllRequest | None = None,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Marque tout comme lu, eventuellement pour une seule categorie."""
    category = payload.category if payload else None
    updated = await notification_repo.mark_all_read(session, category)
    return {
        "updated": updated,
        "category": category.value if category else None,
        "unread": await notification_repo.unread_count(session),
    }


@router.delete("")
async def delete_all_notifications(
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Vide entierement la boite de reception.

    Marquer comme lu ne suffisait pas : rien ne disparaissait jamais, et la
    liste devenait illisible au bout de quelques heures.
    """
    deleted = await notification_repo.delete_all(session)
    await journal.record(
        session,
        event="notifications_videes",
        message=f"{deleted} notification(s) effacee(s) a la demande",
        category="system",
    )
    return {"deleted": deleted, "unread": 0}


# ---------------------------------------------------------------------------
# Preferences et diagnostic (declarees avant /{id} pour eviter toute collision)
# ---------------------------------------------------------------------------

@router.get("/preferences")
async def get_preferences(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Reglages de toutes les categories, valeurs par defaut comprises."""
    preferences = await notification_repo.all_preferences(session)
    return {
        "preferences": [_preference_payload(item) for item in preferences],
        "priorities": [item.value for item in NotificationPriority],
        "defaultPushPriorities": [
            NotificationPriority.HIGH.value,
            NotificationPriority.CRITICAL.value,
        ],
    }


@router.put("/preferences")
async def update_preferences(
    payload: PreferencesRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Met a jour une ou plusieurs categories (CDC2 sections 64, 66 et 90)."""
    if not payload.preferences:
        raise HTTPException(status_code=400, detail="Aucune préférence fournie")
    for update in payload.preferences:
        changes = update.model_dump(exclude_none=True, exclude={"category"})
        await notification_repo.update_preference(session, update.category, changes)
    preferences = await notification_repo.all_preferences(session)
    return {"preferences": [_preference_payload(item) for item in preferences]}


@router.get("/push/status")
async def push_status(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """FCM configure ou non, et ce qui prend le relais dans le cas contraire."""
    return await notification_service.push_status(session)


@router.post("/test")
async def send_test_notification(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Envoie une notification d'essai vers l'inbox, le WebSocket et FCM."""
    return await notification_service.send_test(session)


@router.get("/{notification_id}")
async def get_notification(
    notification_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    event = await notification_repo.get_event(session, notification_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Notification inconnue")
    return event_payload(event)


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    event = await notification_repo.mark_read(session, notification_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Notification inconnue")
    return {
        "notification": event_payload(event),
        "unread": await notification_repo.unread_count(session),
    }
