"""Anti-spam des notifications : pertinence, doublons et plages de silence.

CDC2 section 64 (push HIGH et CRITICAL seulement, MEDIUM dans l'application) et
section 90 (quiet hours, derogation CRITICAL). Aucun test n'ouvre de connexion :
le moteur de pertinence est une fonction pure, le service travaille sur la base
en memoire.
"""

from __future__ import annotations

from datetime import datetime, time

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.intelligence import (
    NotificationCategory,
    NotificationPreference,
    NotificationPriority,
)
from app.services.notifications import relevance
from app.services.notifications.fcm import FcmSendResult
from app.services.notifications.relevance import (
    NotificationRelevanceScore,
    in_quiet_window,
    parse_hhmm,
    quiet_hours_active,
    relevance_score,
)
from app.services.notifications.service import NotificationService

ENGINE = NotificationRelevanceScore()


class StubTransport:
    """Transport push simule : il enregistre, il n'ouvre aucune connexion."""

    configured = True

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def status(self) -> dict[str, object]:
        return {"configured": True, "transport": "stub"}

    async def send(self, tokens: list[str], **kwargs: object) -> FcmSendResult:
        self.calls.append({"tokens": list(tokens), **kwargs})
        return FcmSendResult(sent=max(1, len(tokens)))


def preference(
    category: NotificationCategory = NotificationCategory.TRADE, **changes: object
) -> NotificationPreference:
    """Preference en memoire, valeurs par defaut du modele."""
    return NotificationPreference(category=category, **changes)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Priorites (CDC2 section 64)
# ---------------------------------------------------------------------------

def test_par_defaut_seules_high_et_critical_partent_en_push() -> None:
    pref = preference()
    verdicts = {
        priority: ENGINE.evaluate(
            category=NotificationCategory.TRADE, priority=priority, preference=pref
        )
        for priority in NotificationPriority
    }
    assert verdicts[NotificationPriority.LOW].push is False
    assert verdicts[NotificationPriority.MEDIUM].push is False
    assert verdicts[NotificationPriority.HIGH].push is True
    assert verdicts[NotificationPriority.CRITICAL].push is True
    # Ce qui ne part pas en push reste consultable dans l'application.
    assert all(verdict.store for verdict in verdicts.values())
    assert verdicts[NotificationPriority.MEDIUM].reason == relevance.REASON_BELOW_MINIMUM


def test_categorie_desactivee_nest_meme_pas_enregistree() -> None:
    verdict = ENGINE.evaluate(
        category=NotificationCategory.NEWS,
        priority=NotificationPriority.CRITICAL,
        preference=preference(NotificationCategory.NEWS, enabled=False),
    )
    assert verdict.store is False
    assert verdict.push is False
    assert verdict.reason == relevance.REASON_CATEGORY_DISABLED


def test_push_desactive_garde_la_notification_dans_l_application() -> None:
    verdict = ENGINE.evaluate(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        preference=preference(push_enabled=False),
    )
    assert (verdict.store, verdict.push) == (True, False)
    assert verdict.reason == relevance.REASON_PUSH_DISABLED


def test_score_croissant_avec_la_priorite() -> None:
    scores = [
        relevance_score(NotificationCategory.TRADE, priority) for priority in NotificationPriority
    ]
    assert scores == sorted(scores)
    assert 0.0 <= scores[0] <= scores[-1] <= 1.0
    # Un doublon effondre le score sans jamais le rendre negatif.
    duplicate = relevance_score(
        NotificationCategory.TRADE, NotificationPriority.HIGH, duplicate=True
    )
    assert 0.0 <= duplicate < relevance_score(
        NotificationCategory.TRADE, NotificationPriority.HIGH
    )


# ---------------------------------------------------------------------------
# Plages de silence (CDC2 section 90)
# ---------------------------------------------------------------------------

def test_plage_de_silence_traverse_minuit() -> None:
    start, end = time(22, 0), time(7, 0)
    assert in_quiet_window(time(23, 30), start, end) is True
    assert in_quiet_window(time(3, 0), start, end) is True
    assert in_quiet_window(time(7, 0), start, end) is False
    assert in_quiet_window(time(12, 0), start, end) is False
    # Une plage vide ou identique ne fait jamais silence.
    assert in_quiet_window(time(12, 0), time(9, 0), time(9, 0)) is False


def test_heures_illisibles_desactivent_la_plage() -> None:
    assert parse_hhmm("22:30") == time(22, 30)
    assert parse_hhmm("7:5") == time(7, 5)
    for invalid in (None, "", "   ", "abc", "25:00", "22:99", "22:xx"):
        assert parse_hhmm(invalid) is None
    pref = preference(quiet_hours_start="pas une heure", quiet_hours_end="07:00")
    assert quiet_hours_active(pref, datetime(2026, 1, 1, 23, 0)) is False


def test_silence_bloque_high_mais_critical_peut_deroger() -> None:
    nuit = datetime(2026, 1, 1, 23, 30)
    pref = preference(quiet_hours_start="22:00", quiet_hours_end="07:00")

    haute = ENGINE.evaluate(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        preference=pref,
        now=nuit,
    )
    assert (haute.store, haute.push) == (True, False)
    assert haute.reason == relevance.REASON_QUIET_HOURS

    critique = ENGINE.evaluate(
        category=NotificationCategory.RISK,
        priority=NotificationPriority.CRITICAL,
        preference=pref,
        now=nuit,
    )
    assert critique.push is True

    pref.critical_bypasses_quiet_hours = False
    sans_derogation = ENGINE.evaluate(
        category=NotificationCategory.RISK,
        priority=NotificationPriority.CRITICAL,
        preference=pref,
        now=nuit,
    )
    assert sans_derogation.push is False


def test_hors_plage_le_push_repart() -> None:
    pref = preference(quiet_hours_start="22:00", quiet_hours_end="07:00")
    verdict = ENGINE.evaluate(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        preference=pref,
        now=datetime(2026, 1, 1, 10, 0),
    )
    assert verdict.push is True


# ---------------------------------------------------------------------------
# Debit et transport
# ---------------------------------------------------------------------------

def test_limite_de_debit_epargne_les_notifications_critiques() -> None:
    pref = preference()
    sature = ENGINE.evaluate(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        preference=pref,
        pushes_last_hour=ENGINE.max_push_per_hour,
    )
    assert (sature.store, sature.push) == (True, False)
    assert sature.reason == relevance.REASON_RATE_LIMITED

    critique = ENGINE.evaluate(
        category=NotificationCategory.RISK,
        priority=NotificationPriority.CRITICAL,
        preference=preference(NotificationCategory.RISK),
        pushes_last_hour=ENGINE.max_push_per_hour * 5,
    )
    assert critique.push is True


def test_sans_transport_la_notification_reste_disponible() -> None:
    verdict = ENGINE.evaluate(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.CRITICAL,
        preference=preference(),
        transport_ready=False,
    )
    assert (verdict.store, verdict.push) == (True, False)
    assert verdict.reason == relevance.REASON_NO_TRANSPORT
    assert "FCM" in verdict.detail


# ---------------------------------------------------------------------------
# Deduplication reelle, via le service et la base
# ---------------------------------------------------------------------------

async def test_la_meme_alerte_ne_part_pas_dix_fois(session: AsyncSession) -> None:
    """CDC2 section 64 : dix appels identiques, une seule notification."""
    service = NotificationService(transport=StubTransport())
    events = []
    for _ in range(10):
        event = await service.notify(
            NotificationCategory.TRADE,
            NotificationPriority.HIGH,
            "🔴 STOP LOSS — XAUUSD",
            "XAUUSD · VENTE",
            symbol="XAUUSD",
            session=session,
        )
        events.append(event)

    assert events[0] is not None
    assert all(event is None for event in events[1:])
    assert len(service.transport.calls) == 1


async def test_le_doublon_est_juge_par_symbole(session: AsyncSession) -> None:
    service = NotificationService(transport=StubTransport())
    first = await service.notify(
        NotificationCategory.TRADE,
        NotificationPriority.HIGH,
        "🟢 ACHAT OUVERT",
        "corps",
        symbol="XAUUSD",
        session=session,
    )
    second = await service.notify(
        NotificationCategory.TRADE,
        NotificationPriority.HIGH,
        "🟢 ACHAT OUVERT",
        "corps",
        symbol="EURUSD",
        session=session,
    )
    assert first is not None and second is not None
    assert first.id != second.id


async def test_medium_reste_dans_l_application(session: AsyncSession) -> None:
    service = NotificationService(transport=StubTransport())
    event = await service.notify(
        NotificationCategory.TRADE,
        NotificationPriority.MEDIUM,
        "🛡 BREAK EVEN ACTIVÉ — XAUUSD",
        "SL déplacé : 3512.40",
        symbol="XAUUSD",
        session=session,
    )
    assert event is not None
    assert event.pushed is False
    assert event.push_error == relevance.REASON_BELOW_MINIMUM
    assert service.transport.calls == []
