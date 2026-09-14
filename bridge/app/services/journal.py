"""Service de journalisation fonctionnelle.

Un evenement important est ecrit trois fois :
 - dans le fichier de log rotatif (technique, secrets masques) ;
 - dans la table ``journal_entries`` (visible dans l'application) ;
 - sur le bus d'evenements (temps reel).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger, redact
from app.database.session import session_scope
from app.models.enums import EventLevel
from app.repositories import journal_repo
from app.services.events import EventType, event_bus

logger = get_logger("tradepilot.journal")

_LEVEL_TO_LOG = {
    EventLevel.DEBUG: logger.debug,
    EventLevel.INFO: logger.info,
    EventLevel.WARNING: logger.warning,
    EventLevel.ERROR: logger.error,
    EventLevel.CRITICAL: logger.critical,
}


async def record(
    session: AsyncSession,
    event: str,
    message: str,
    level: EventLevel = EventLevel.INFO,
    category: str = "system",
    channel_id: int | None = None,
    signal_id: int | None = None,
    data: dict[str, Any] | None = None,
    broadcast: bool = True,
) -> None:
    """Ecrit une entree de journal dans une session existante."""
    safe_message = redact(message)
    _LEVEL_TO_LOG.get(level, logger.info)("[%s] %s", event, safe_message)
    entry = await journal_repo.add_entry(
        session,
        event=event,
        message=safe_message,
        level=level,
        category=category,
        channel_id=channel_id,
        signal_id=signal_id,
        data=data,
    )
    if broadcast:
        event_bus.publish(
            EventType.JOURNAL,
            {
                "id": entry.id,
                "event": event,
                "message": safe_message,
                "level": level.value,
                "category": category,
                "channelId": channel_id,
                "signalId": signal_id,
                "createdAt": entry.created_at.isoformat(),
            },
        )


async def log(
    event: str,
    message: str,
    level: EventLevel = EventLevel.INFO,
    category: str = "system",
    channel_id: int | None = None,
    signal_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Variante autonome : ouvre sa propre session (services de fond)."""
    try:
        async with session_scope() as session:
            await record(
                session,
                event=event,
                message=message,
                level=level,
                category=category,
                channel_id=channel_id,
                signal_id=signal_id,
                data=data,
            )
    except Exception:  # la journalisation ne doit jamais interrompre le moteur
        logger.exception("Echec d'ecriture du journal pour %s", event)


async def audit(
    session: AsyncSession,
    action: str,
    actor: str = "system",
    target: str | None = None,
    signal_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    await journal_repo.add_audit(
        session, action=action, actor=actor, target=target, signal_id=signal_id, details=details
    )
