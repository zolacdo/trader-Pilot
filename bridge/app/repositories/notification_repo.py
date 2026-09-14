"""Acces aux notifications : inbox, preferences par categorie, jetons push.

Les tables sont definies dans ``app.models.intelligence`` (NotificationEvent,
NotificationPreference) et ne sont jamais modifiees ici.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import Device, utcnow
from app.models.intelligence import (
    NotificationCategory,
    NotificationEvent,
    NotificationPreference,
    NotificationPriority,
)

# Champs qu'une requete cliente n'a pas le droit de reecrire.
PROTECTED_PREFERENCE_FIELDS = {"id", "category", "updated_at"}


# ---------------------------------------------------------------------------
# Inbox (CDC2 section 67)
# ---------------------------------------------------------------------------

async def create_event(
    session: AsyncSession,
    *,
    category: NotificationCategory,
    priority: NotificationPriority,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    symbol: str | None = None,
    decision_id: int | None = None,
    news_id: int | None = None,
) -> NotificationEvent:
    """Enregistre une notification. C'est la trace durable, meme sans push."""
    event = NotificationEvent(
        category=category,
        priority=priority,
        title=title[:255],
        body=body,
        data=data,
        symbol=symbol[:32] if symbol else None,
        decision_id=decision_id,
        news_id=news_id,
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    category: NotificationCategory | None = None,
    priority: NotificationPriority | None = None,
    symbol: str | None = None,
    unread_only: bool = False,
    since: datetime | None = None,
) -> list[NotificationEvent]:
    statement = select(NotificationEvent)
    statement = _apply_filters(
        statement,
        category=category,
        priority=priority,
        symbol=symbol,
        unread_only=unread_only,
        since=since,
    )
    statement = statement.order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc())
    result = await session.exec(statement.offset(offset).limit(limit))
    return list(result.all())


async def count_events(
    session: AsyncSession,
    *,
    category: NotificationCategory | None = None,
    priority: NotificationPriority | None = None,
    symbol: str | None = None,
    unread_only: bool = False,
    since: datetime | None = None,
) -> int:
    statement = select(func.count()).select_from(NotificationEvent)
    statement = _apply_filters(
        statement,
        category=category,
        priority=priority,
        symbol=symbol,
        unread_only=unread_only,
        since=since,
    )
    result = await session.exec(statement)
    return int(result.one())


def _apply_filters(
    statement: Any,
    *,
    category: NotificationCategory | None,
    priority: NotificationPriority | None,
    symbol: str | None,
    unread_only: bool,
    since: datetime | None,
) -> Any:
    if category is not None:
        statement = statement.where(NotificationEvent.category == category)
    if priority is not None:
        statement = statement.where(NotificationEvent.priority == priority)
    if symbol:
        statement = statement.where(NotificationEvent.symbol == symbol)
    if unread_only:
        statement = statement.where(NotificationEvent.read_at == None)  # noqa: E711
    if since is not None:
        statement = statement.where(NotificationEvent.created_at >= since)
    return statement


async def get_event(session: AsyncSession, event_id: int) -> NotificationEvent | None:
    return await session.get(NotificationEvent, event_id)


async def mark_read(session: AsyncSession, event_id: int) -> NotificationEvent | None:
    event = await session.get(NotificationEvent, event_id)
    if event is None:
        return None
    if event.read_at is None:
        event.read_at = utcnow()
        session.add(event)
        await session.flush()
    return event


async def mark_all_read(
    session: AsyncSession, category: NotificationCategory | None = None
) -> int:
    statement = select(NotificationEvent).where(NotificationEvent.read_at == None)  # noqa: E711
    if category is not None:
        statement = statement.where(NotificationEvent.category == category)
    result = await session.exec(statement)
    now = utcnow()
    count = 0
    for event in result.all():
        event.read_at = now
        session.add(event)
        count += 1
    if count:
        await session.flush()
    return count


async def unread_count(session: AsyncSession) -> int:
    return await count_events(session, unread_only=True)


async def unread_by_category(session: AsyncSession) -> dict[str, int]:
    statement = (
        select(NotificationEvent.category, func.count())
        .where(NotificationEvent.read_at == None)  # noqa: E711
        .group_by(NotificationEvent.category)
    )
    result = await session.exec(statement)
    return {str(getattr(row[0], "value", row[0])): int(row[1]) for row in result.all()}


async def mark_push_result(
    session: AsyncSession, event: NotificationEvent, *, pushed: bool, error: str | None = None
) -> NotificationEvent:
    """Trace le resultat de l'envoi distant, sans jamais stocker de secret."""
    event.pushed = pushed
    event.push_error = error[:255] if error else None
    session.add(event)
    await session.flush()
    return event


async def find_recent_similar(
    session: AsyncSession,
    *,
    category: NotificationCategory,
    title: str,
    symbol: str | None,
    within: timedelta,
    now: datetime | None = None,
) -> NotificationEvent | None:
    """Anti-doublon : meme categorie, meme symbole, meme titre dans la fenetre."""
    reference = now or utcnow()
    statement = (
        select(NotificationEvent)
        .where(NotificationEvent.category == category)
        .where(NotificationEvent.title == title[:255])
        .where(NotificationEvent.created_at >= reference - within)
    )
    if symbol:
        statement = statement.where(NotificationEvent.symbol == symbol[:32])
    else:
        statement = statement.where(NotificationEvent.symbol == None)  # noqa: E711
    statement = statement.order_by(NotificationEvent.created_at.desc())
    result = await session.exec(statement)
    return result.first()


async def count_pushed_since(session: AsyncSession, since: datetime) -> int:
    """Nombre de push reellement partis depuis un instant (limite de debit)."""
    statement = (
        select(func.count())
        .select_from(NotificationEvent)
        .where(NotificationEvent.pushed == True)
        .where(NotificationEvent.created_at >= since)
    )
    result = await session.exec(statement)
    return int(result.one())


async def purge_older_than(
    session: AsyncSession, cutoff: datetime, *, only_read: bool = False
) -> int:
    """Entretien de l'inbox : les notifications anciennes disparaissent.

    ``only_read`` limite la purge a ce qui a ete lu. C'etait l'ancien
    comportement, et il ne nettoyait rien : une depeche jamais ouverte restait
    indefiniment. Par defaut on efface donc tout ce qui a passe l'age, lu ou
    non -- une alerte vieille de plusieurs heures n'a plus rien a signaler.
    """
    statement = select(NotificationEvent).where(NotificationEvent.created_at < cutoff)
    if only_read:
        statement = statement.where(NotificationEvent.read_at != None)  # noqa: E711
    result = await session.exec(statement)
    count = 0
    for event in result.all():
        await session.delete(event)
        count += 1
    if count:
        await session.flush()
    return count


async def delete_all(session: AsyncSession) -> int:
    """Vide entierement la boite de reception, a la demande de l'utilisateur."""
    result = await session.exec(select(NotificationEvent))
    count = 0
    for event in result.all():
        await session.delete(event)
        count += 1
    if count:
        await session.flush()
    return count


# ---------------------------------------------------------------------------
# Preferences par categorie (CDC2 sections 64, 66 et 90)
# ---------------------------------------------------------------------------

async def get_preference(
    session: AsyncSession, category: NotificationCategory
) -> NotificationPreference:
    """Preference de la categorie, creee avec les valeurs par defaut si absente."""
    result = await session.exec(
        select(NotificationPreference).where(NotificationPreference.category == category)
    )
    preference = result.first()
    if preference is None:
        preference = NotificationPreference(category=category)
        session.add(preference)
        await session.flush()
    return preference


async def all_preferences(session: AsyncSession) -> list[NotificationPreference]:
    """Toutes les categories, dans l'ordre de l'enumeration du CDC2."""
    preferences: list[NotificationPreference] = []
    for category in NotificationCategory:
        preferences.append(await get_preference(session, category))
    return preferences


async def update_preference(
    session: AsyncSession, category: NotificationCategory, changes: dict[str, Any]
) -> NotificationPreference:
    preference = await get_preference(session, category)
    for key, value in changes.items():
        if key in PROTECTED_PREFERENCE_FIELDS or value is None:
            continue
        if hasattr(preference, key):
            setattr(preference, key, value)
    preference.updated_at = utcnow()
    session.add(preference)
    await session.flush()
    return preference


# ---------------------------------------------------------------------------
# Jetons d'appareil (alimentes par /api/v1/devices/push-token)
# ---------------------------------------------------------------------------

async def push_targets(session: AsyncSession) -> list[Device]:
    """Appareils actifs disposant d'un jeton push."""
    statement = (
        select(Device)
        .where(Device.revoked == False)
        .where(Device.push_token != None)  # noqa: E711
    )
    result = await session.exec(statement)
    return [device for device in result.all() if (device.push_token or "").strip()]


async def clear_push_token(session: AsyncSession, device_id: str) -> None:
    """Oublie un jeton refuse par FCM (appareil desinstalle ou reinstalle)."""
    result = await session.exec(select(Device).where(Device.device_id == device_id))
    device = result.first()
    if device is not None:
        device.push_token = None
        session.add(device)
        await session.flush()
