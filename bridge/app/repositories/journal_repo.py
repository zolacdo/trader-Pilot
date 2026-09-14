"""Persistance du journal fonctionnel et des traces d'audit."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import AuditLog, EventLevel, JournalEntry


async def add_entry(
    session: AsyncSession,
    event: str,
    message: str,
    level: EventLevel = EventLevel.INFO,
    category: str = "system",
    channel_id: int | None = None,
    signal_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> JournalEntry:
    entry = JournalEntry(
        event=event,
        message=message,
        level=level,
        category=category,
        channel_id=channel_id,
        signal_id=signal_id,
        data=data,
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_entries(
    session: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    level: EventLevel | None = None,
    category: str | None = None,
    channel_id: int | None = None,
    signal_id: int | None = None,
    since: datetime | None = None,
) -> list[JournalEntry]:
    statement = select(JournalEntry)
    if level is not None:
        statement = statement.where(JournalEntry.level == level)
    if category is not None:
        statement = statement.where(JournalEntry.category == category)
    if channel_id is not None:
        statement = statement.where(JournalEntry.channel_id == channel_id)
    if signal_id is not None:
        statement = statement.where(JournalEntry.signal_id == signal_id)
    if since is not None:
        statement = statement.where(JournalEntry.created_at >= since)
    statement = statement.order_by(JournalEntry.created_at.desc()).offset(offset).limit(limit)
    result = await session.exec(statement)
    return list(result.all())


async def count_entries(session: AsyncSession, level: EventLevel | None = None) -> int:
    statement = select(func.count()).select_from(JournalEntry)
    if level is not None:
        statement = statement.where(JournalEntry.level == level)
    result = await session.exec(statement)
    return int(result.one())


async def purge_entries(session: AsyncSession, keep_last: int = 20000) -> int:
    """Conserve les N entrees les plus recentes, supprime le reste."""
    total = await count_entries(session)
    if total <= keep_last:
        return 0
    result = await session.exec(
        select(JournalEntry.id).order_by(JournalEntry.created_at.desc()).offset(keep_last)
    )
    ids = list(result.all())
    for entry_id in ids:
        entry = await session.get(JournalEntry, entry_id)
        if entry is not None:
            await session.delete(entry)
    await session.flush()
    return len(ids)


async def add_audit(
    session: AsyncSession,
    action: str,
    actor: str = "system",
    target: str | None = None,
    signal_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(action=action, actor=actor, target=target, signal_id=signal_id, details=details)
    session.add(log)
    await session.flush()
    return log


async def list_audit(
    session: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    signal_id: int | None = None,
) -> list[AuditLog]:
    statement = select(AuditLog)
    if signal_id is not None:
        statement = statement.where(AuditLog.signal_id == signal_id)
    statement = statement.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    result = await session.exec(statement)
    return list(result.all())
