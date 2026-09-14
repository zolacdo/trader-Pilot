"""Notifications TradePilot (CDC2 sections 50 a 67, 87 a 90 et 94).

Point d'entree unique : ``notification_service.notify(...)`` ou
``notification_service.send(draft)`` avec un gabarit de ``templates``.
"""

from app.services.notifications import reports, templates
from app.services.notifications.fcm import FcmSendResult, FcmTransport, fcm_transport
from app.services.notifications.formatting import NotificationDraft
from app.services.notifications.movement import (
    MovementAlert,
    MovementThresholds,
    detect_movements,
    evaluate_market_movement,
)
from app.services.notifications.relevance import (
    NotificationRelevanceScore,
    RelevanceVerdict,
    relevance_engine,
)
from app.services.notifications.service import (
    NotificationService,
    event_payload,
    notification_service,
)

__all__ = [
    "FcmSendResult",
    "FcmTransport",
    "MovementAlert",
    "MovementThresholds",
    "NotificationDraft",
    "NotificationRelevanceScore",
    "NotificationService",
    "RelevanceVerdict",
    "detect_movements",
    "evaluate_market_movement",
    "event_payload",
    "fcm_transport",
    "notification_service",
    "relevance_engine",
    "reports",
    "templates",
]
