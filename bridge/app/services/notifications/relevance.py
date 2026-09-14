"""NotificationRelevanceScore : ce qui merite de faire vibrer le telephone.

CDC2 section 64 : par defaut, seules les priorites HIGH et CRITICAL partent en
push ; MEDIUM reste dans l'application. CDC2 section 90 : des plages de silence
sont configurables, avec derogation possible pour les notifications CRITICAL.

Le module est volontairement pur : il ne touche ni la base, ni le reseau. Il
recoit un etat, il rend un verdict. Cela le rend testable sans aucun acces
externe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.models.intelligence import (
    NotificationCategory,
    NotificationPreference,
    NotificationPriority,
)

PRIORITY_RANK: dict[NotificationPriority, int] = {
    NotificationPriority.LOW: 0,
    NotificationPriority.MEDIUM: 1,
    NotificationPriority.HIGH: 2,
    NotificationPriority.CRITICAL: 3,
}

# Fenetre anti-doublon : la meme alerte sur le meme symbole ne repart pas.
DEDUP_WINDOWS: dict[NotificationPriority, timedelta] = {
    NotificationPriority.CRITICAL: timedelta(minutes=5),
    NotificationPriority.HIGH: timedelta(minutes=15),
    NotificationPriority.MEDIUM: timedelta(minutes=30),
    NotificationPriority.LOW: timedelta(minutes=60),
}

# Poids par categorie : une limite de risque compte plus qu'une info de marche.
CATEGORY_WEIGHT: dict[NotificationCategory, float] = {
    NotificationCategory.RISK: 1.0,
    NotificationCategory.TRADE: 0.95,
    NotificationCategory.SIGNAL: 0.8,
    NotificationCategory.OPPORTUNITY: 0.75,
    NotificationCategory.AI_SYSTEM: 0.7,
    NotificationCategory.SYSTEM: 0.7,
    NotificationCategory.ECONOMIC: 0.6,
    NotificationCategory.NEWS: 0.55,
    NotificationCategory.DAILY_REPORT: 0.5,
}

# Plafond de push non critiques sur une heure glissante : un moteur emballe ne
# doit jamais transformer le telephone en sonnerie continue.
MAX_PUSH_PER_HOUR = 12

# Codes de verdict, repris tels quels dans le champ push_error et l'inbox.
REASON_DELIVERED = "PUSH"
REASON_CATEGORY_DISABLED = "CATEGORY_DISABLED"
REASON_DUPLICATE = "DUPLICATE"
REASON_PUSH_DISABLED = "PUSH_DISABLED"
REASON_BELOW_MINIMUM = "BELOW_MINIMUM_PRIORITY"
REASON_QUIET_HOURS = "QUIET_HOURS"
REASON_RATE_LIMITED = "RATE_LIMITED"
REASON_NO_TRANSPORT = "PUSH_TRANSPORT_UNAVAILABLE"

REASON_LABELS: dict[str, str] = {
    REASON_DELIVERED: "Envoyée en notification push.",
    REASON_CATEGORY_DISABLED: "Catégorie désactivée par l’utilisateur.",
    REASON_DUPLICATE: "Alerte identique déjà envoyée récemment.",
    REASON_PUSH_DISABLED: "Push désactivé pour cette catégorie, gardée dans l’application.",
    REASON_BELOW_MINIMUM: "Priorité insuffisante pour un push, gardée dans l’application.",
    REASON_QUIET_HOURS: "Plage de silence active.",
    REASON_RATE_LIMITED: "Trop de notifications récentes, celle-ci reste dans l’application.",
    REASON_NO_TRANSPORT: "FCM non configuré : repli WebSocket et inbox interne.",
}


@dataclass(frozen=True, slots=True)
class RelevanceVerdict:
    """Decision complete : garder, pousser, et pourquoi."""

    store: bool
    push: bool
    score: float
    reason: str

    @property
    def detail(self) -> str:
        return REASON_LABELS.get(self.reason, self.reason)


def priority_rank(priority: NotificationPriority) -> int:
    return PRIORITY_RANK.get(priority, 0)


def dedup_window(priority: NotificationPriority) -> timedelta:
    return DEDUP_WINDOWS.get(priority, timedelta(minutes=30))


def parse_hhmm(value: str | None) -> time | None:
    """Lit "22:30". Toute valeur illisible desactive la plage, sans exception."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        hour_text, _, minute_text = text.partition(":")
        hour = int(hour_text)
        minute = int(minute_text or 0)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def in_quiet_window(moment: time, start: time, end: time) -> bool:
    """Gere les plages qui traversent minuit (22:00 -> 07:00)."""
    if start == end:
        return False
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


def quiet_hours_active(preference: NotificationPreference, now: datetime | None = None) -> bool:
    """Plage de silence de la categorie, evaluee a l'heure locale du Bridge."""
    start = parse_hhmm(preference.quiet_hours_start)
    end = parse_hhmm(preference.quiet_hours_end)
    if start is None or end is None:
        return False
    moment = (now or datetime.now()).time()
    return in_quiet_window(moment, start, end)


def relevance_score(
    category: NotificationCategory,
    priority: NotificationPriority,
    *,
    duplicate: bool = False,
    confidence: float | None = None,
) -> float:
    """Score 0..1 : priorite d'abord, categorie ensuite, confiance en appoint."""
    base = priority_rank(priority) / 3.0
    weight = CATEGORY_WEIGHT.get(category, 0.5)
    score = 0.65 * base + 0.35 * weight
    if confidence is not None:
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            value = 0.0
        if value > 1.0:
            value /= 100.0
        score = 0.85 * score + 0.15 * max(0.0, min(1.0, value))
    if duplicate:
        score *= 0.25
    return round(max(0.0, min(1.0, score)), 3)


class NotificationRelevanceScore:
    """Arbitre unique de l'anti-spam (CDC2 section 64)."""

    def __init__(self, max_push_per_hour: int = MAX_PUSH_PER_HOUR) -> None:
        self.max_push_per_hour = max_push_per_hour

    def evaluate(
        self,
        *,
        category: NotificationCategory,
        priority: NotificationPriority,
        preference: NotificationPreference,
        duplicate: bool = False,
        pushes_last_hour: int = 0,
        transport_ready: bool = True,
        confidence: float | None = None,
        now: datetime | None = None,
    ) -> RelevanceVerdict:
        score = relevance_score(category, priority, duplicate=duplicate, confidence=confidence)
        is_critical = priority == NotificationPriority.CRITICAL

        if not preference.enabled:
            return RelevanceVerdict(False, False, score, REASON_CATEGORY_DISABLED)
        if duplicate:
            return RelevanceVerdict(False, False, score, REASON_DUPLICATE)
        if not preference.push_enabled:
            return RelevanceVerdict(True, False, score, REASON_PUSH_DISABLED)
        if priority_rank(priority) < priority_rank(preference.minimum_priority):
            return RelevanceVerdict(True, False, score, REASON_BELOW_MINIMUM)

        silent = quiet_hours_active(preference, now)
        if silent and not (is_critical and preference.critical_bypasses_quiet_hours):
            return RelevanceVerdict(True, False, score, REASON_QUIET_HOURS)

        if not is_critical and pushes_last_hour >= self.max_push_per_hour:
            return RelevanceVerdict(True, False, score, REASON_RATE_LIMITED)
        if not transport_ready:
            return RelevanceVerdict(True, False, score, REASON_NO_TRANSPORT)

        return RelevanceVerdict(True, True, score, REASON_DELIVERED)


relevance_engine = NotificationRelevanceScore()
