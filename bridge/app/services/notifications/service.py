"""NotificationService : point d'entree unique des notifications (CDC2 50 a 67).

Chaque notification suit toujours le meme chemin :

1. nettoyage de securite (CDC2 section 94) ;
2. preference de la categorie et anti-doublon ;
3. enregistrement dans ``notification_events`` (l'inbox, qui survit a tout) ;
4. publication sur le bus d'evenements -> WebSocket (repli sans FCM) ;
5. tentative de push distant si, et seulement si, le score de pertinence le
   justifie.

Le systeme fonctionne entierement sans Firebase : dans ce cas l'etape 5 se
contente d'inscrire la raison dans ``push_error`` et le diagnostic le dit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.database.session import session_scope
from app.models.core import utcnow
from app.models.intelligence import (
    NotificationCategory,
    NotificationEvent,
    NotificationPriority,
)
from app.repositories import notification_repo
from app.services.events import EventType, event_bus
from app.services.notifications import templates
from app.services.notifications.fcm import FcmTransport, fcm_transport
from app.services.notifications.formatting import NotificationDraft
from app.services.notifications.relevance import (
    NotificationRelevanceScore,
    RelevanceVerdict,
    dedup_window,
    relevance_engine,
)
from app.services.notifications.safety import sanitize_draft_fields

logger = get_logger(__name__)

PUSH_PRIORITIES = {NotificationPriority.HIGH, NotificationPriority.CRITICAL}


def event_payload(event: NotificationEvent, verdict: RelevanceVerdict | None = None) -> dict[str, Any]:
    """Representation JSON envoyee au WebSocket et a l'API."""
    payload: dict[str, Any] = {
        "id": event.id,
        "createdAt": event.created_at.isoformat(),
        "category": event.category.value,
        "priority": event.priority.value,
        "title": event.title,
        "body": event.body,
        "data": event.data or {},
        "symbol": event.symbol,
        "decisionId": event.decision_id,
        "newsId": event.news_id,
        "pushed": event.pushed,
        "pushError": event.push_error,
        "readAt": event.read_at.isoformat() if event.read_at else None,
    }
    if verdict is not None:
        payload["relevance"] = {
            "score": verdict.score,
            "reason": verdict.reason,
            "detail": verdict.detail,
        }
    return payload


@asynccontextmanager
async def _use_session(session: AsyncSession | None) -> AsyncIterator[AsyncSession]:
    """Reutilise la session de l'appelant, ou en ouvre une le temps de l'ecriture."""
    if session is not None:
        yield session
        return
    async with session_scope() as owned:
        yield owned


class NotificationService:
    """Fabrique, garde et distribue les notifications du Bridge."""

    def __init__(
        self,
        transport: FcmTransport | None = None,
        relevance: NotificationRelevanceScore | None = None,
    ) -> None:
        self.transport = transport or fcm_transport
        self.relevance = relevance or relevance_engine

    # -- API principale ---------------------------------------------------

    async def notify(
        self,
        category: NotificationCategory,
        priority: NotificationPriority,
        title: str,
        body: str,
        *,
        data: dict[str, Any] | None = None,
        symbol: str | None = None,
        decision_id: int | None = None,
        news_id: int | None = None,
        confidence: float | None = None,
        collapse_key: str | None = None,
        session: AsyncSession | None = None,
    ) -> NotificationEvent | None:
        """Enregistre, diffuse et pousse une notification. None = ecartee."""
        safe_title, safe_body, safe_data = sanitize_draft_fields(title, body, data)
        if not safe_title:
            return None

        async with _use_session(session) as db_session:
            preference = await notification_repo.get_preference(db_session, category)
            duplicate = await notification_repo.find_recent_similar(
                db_session,
                category=category,
                title=safe_title,
                symbol=symbol,
                within=dedup_window(priority),
            )
            pushes_last_hour = await notification_repo.count_pushed_since(
                db_session, utcnow() - timedelta(hours=1)
            )
            verdict = self.relevance.evaluate(
                category=category,
                priority=priority,
                preference=preference,
                duplicate=duplicate is not None,
                pushes_last_hour=pushes_last_hour,
                transport_ready=self.transport.configured,
                confidence=confidence,
            )
            if not verdict.store:
                logger.debug("Notification ecartee (%s) : %s", verdict.reason, safe_title)
                return None

            event = await notification_repo.create_event(
                db_session,
                category=category,
                priority=priority,
                title=safe_title,
                body=safe_body,
                data=safe_data or None,
                symbol=symbol,
                decision_id=decision_id,
                news_id=news_id,
            )

            if verdict.push:
                await self._push(db_session, event, collapse_key=collapse_key)
            else:
                await notification_repo.mark_push_result(
                    db_session, event, pushed=False, error=verdict.reason
                )

            event_bus.publish(EventType.NOTIFICATION_CREATED, event_payload(event, verdict))
            return event

    async def send(
        self,
        draft: NotificationDraft,
        *,
        confidence: float | None = None,
        collapse_key: str | None = None,
        session: AsyncSession | None = None,
    ) -> NotificationEvent | None:
        """Envoie un gabarit pret a l'emploi (``templates``)."""
        return await self.notify(
            draft.category,
            draft.priority,
            draft.title,
            draft.body,
            data=draft.data,
            symbol=draft.symbol,
            decision_id=draft.decision_id,
            news_id=draft.news_id,
            confidence=confidence,
            collapse_key=collapse_key,
            session=session,
        )

    async def send_many(
        self, drafts: list[NotificationDraft], *, session: AsyncSession | None = None
    ) -> list[NotificationEvent]:
        events: list[NotificationEvent] = []
        async with _use_session(session) as db_session:
            for draft in drafts:
                event = await self.send(draft, session=db_session)
                if event is not None:
                    events.append(event)
        return events

    async def send_test(self, session: AsyncSession | None = None) -> dict[str, Any]:
        """Notification d'essai : elle ignore l'anti-doublon pour rester utile."""
        draft = templates.test_notification()
        draft.title = f"{draft.title} · {utcnow().strftime('%H:%M:%S')}"
        event = await self.send(draft, session=session)
        if event is None:
            return {"sent": False, "reason": "La catégorie SYSTEM est désactivée."}
        return {
            "sent": True,
            "pushed": event.pushed,
            "reason": event.push_error,
            "notification": event_payload(event),
        }

    # -- transport --------------------------------------------------------

    async def _push(
        self, session: AsyncSession, event: NotificationEvent, *, collapse_key: str | None
    ) -> None:
        devices = await notification_repo.push_targets(session)
        tokens = [device.push_token or "" for device in devices]
        result = await self.transport.send(
            tokens,
            title=event.title,
            body=event.body,
            data=self._push_data(event),
            high_priority=event.priority in PUSH_PRIORITIES,
            collapse_key=collapse_key,
        )
        for invalid in result.invalid_tokens:
            for device in devices:
                if device.push_token == invalid:
                    await notification_repo.clear_push_token(session, device.device_id)
        await notification_repo.mark_push_result(
            session, event, pushed=result.delivered, error=None if result.delivered else result.error
        )

    @staticmethod
    def _push_data(event: NotificationEvent) -> dict[str, Any]:
        """Charge utile du push : navigation seulement, jamais d'ordre."""
        payload = dict(event.data or {})
        payload.update(
            {
                "notificationId": event.id,
                "category": event.category.value,
                "priority": event.priority.value,
            }
        )
        return payload

    # -- diagnostic -------------------------------------------------------

    async def push_status(self, session: AsyncSession | None = None) -> dict[str, Any]:
        """Etat du push, dit franchement (CDC2 sections 50 et 111)."""
        status = dict(self.transport.status())
        async with _use_session(session) as db_session:
            devices = await notification_repo.push_targets(db_session)
            status["devicesWithToken"] = len(devices)
            status["unread"] = await notification_repo.unread_count(db_session)
        status["pushPossible"] = bool(status["configured"] and status["devicesWithToken"])
        if not status["configured"]:
            status["message"] = (
                "Firebase n’est pas configuré : les notifications restent disponibles "
                "par WebSocket, notification locale et inbox interne."
            )
        elif not status["devicesWithToken"]:
            status["message"] = (
                "Firebase est configuré mais aucun téléphone n’a encore enregistré "
                "son jeton via /api/v1/devices/push-token."
            )
        else:
            status["message"] = "Notifications push actives."
        return status


notification_service = NotificationService()
