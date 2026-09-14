"""Tests du calendrier economique (CDC2 sections 33, 34 et 35).

Aucun acces reseau : le point d'acces JSON est servi par un
``httpx.MockTransport``. Sans source configuree, le moteur doit le dire, pas
fabriquer des evenements.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.intelligence import NewsImpact, WatchlistItem
from app.repositories import news_repo
from app.services.economic_calendar.engine import (
    NO_SOURCE_MESSAGE,
    EconomicCalendarEngine,
)
from app.services.economic_calendar.provider import (
    CalendarProviderError,
    JsonCalendarProvider,
    build_client,
    parse_datetime,
)
from app.services.economic_calendar.sources import (
    CalendarOptions,
    CalendarSource,
    load_options,
    save_options,
    save_sources,
)
from app.services.news.risk_mode import BlackoutConfig, evaluate_for_session, save_config

NOW = datetime(2024, 3, 20, 10, 0, tzinfo=UTC)


def _source(**overrides) -> CalendarSource:
    base = {
        "key": "demo",
        "name": "Calendrier de démonstration",
        "url": "https://calendar.test/events.json",
        "items_path": "data.events",
    }
    base.update(overrides)
    return CalendarSource(**base)


def _payload(rows: list[dict]) -> str:
    return json.dumps({"data": {"events": rows}})


def _row(
    event_id: str,
    minutes_from_now: int,
    *,
    title: str = "CPI y/y",
    currency: str = "USD",
    impact: str = "3",
    forecast: str | None = "3.1%",
    previous: str | None = "3.4%",
    actual: str | None = None,
) -> dict:
    return {
        "id": event_id,
        "date": (NOW + timedelta(minutes=minutes_from_now)).isoformat(),
        "title": title,
        "country": "US",
        "currency": currency,
        "impact": impact,
        "forecast": forecast,
        "previous": previous,
        "actual": actual,
    }


def _transport(body: str, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Lecture d'une source JSON configurable
# ---------------------------------------------------------------------------

async def test_json_calendar_is_parsed_with_the_configured_field_map() -> None:
    options = CalendarOptions()
    body = _payload([_row("cpi-mar", 120)])
    async with build_client(options, transport=_transport(body)) as client:
        rows = await JsonCalendarProvider(_source(), options, client=client).fetch()

    assert len(rows) == 1
    event = rows[0]
    assert event.external_id == "demo:cpi-mar"
    assert event.title == "CPI y/y"
    assert event.currency == "USD"
    assert event.impact is NewsImpact.HIGH
    assert event.forecast == "3.1%"
    assert event.previous == "3.4%"
    # Valeur non publiee : elle reste absente, elle n'est pas inventee.
    assert event.actual is None


async def test_custom_field_names_are_honoured() -> None:
    options = CalendarOptions()
    source = _source(
        items_path="",
        field_map={
            "external_id": "ref",
            "scheduled_at": "when",
            "title": "label",
            "currency": "ccy",
            "impact": "importance",
        },
        impact_map={"critique": "HIGH"},
    )
    body = json.dumps(
        [{"ref": "x1", "when": 1710930600, "label": "NFP", "ccy": "usd", "importance": "Critique"}]
    )
    async with build_client(options, transport=_transport(body)) as client:
        rows = await JsonCalendarProvider(source, options, client=client).fetch()

    assert len(rows) == 1
    assert rows[0].title == "NFP"
    assert rows[0].currency == "USD"
    assert rows[0].impact is NewsImpact.HIGH
    assert rows[0].scheduled_at.tzinfo is not None


async def test_rows_without_date_or_title_are_skipped() -> None:
    options = CalendarOptions()
    body = _payload(
        [
            {"id": "a", "title": "Sans date"},
            {"id": "b", "date": NOW.isoformat()},
            _row("c", 30),
            "pas un objet",
        ]
    )
    async with build_client(options, transport=_transport(body)) as client:
        rows = await JsonCalendarProvider(_source(), options, client=client).fetch()
    assert [row.external_id for row in rows] == ["demo:c"]


async def test_unknown_importance_stays_low() -> None:
    options = CalendarOptions()
    body = _payload([_row("z", 60, impact="bizarre")])
    async with build_client(options, transport=_transport(body)) as client:
        rows = await JsonCalendarProvider(_source(), options, client=client).fetch()
    assert rows[0].impact is NewsImpact.LOW


async def test_protected_calendar_is_ignored_not_bypassed() -> None:
    options = CalendarOptions()
    async with build_client(options, transport=_transport("", 403)) as client:
        provider = JsonCalendarProvider(_source(), options, client=client)
        try:
            await provider.fetch()
        except CalendarProviderError as exc:
            assert "contournement" in str(exc)
        else:  # pragma: no cover - le test doit lever
            raise AssertionError("une source protegee doit lever")


def test_dates_are_normalised_to_utc() -> None:
    assert parse_datetime("2024-03-20T12:00:00Z") == datetime(2024, 3, 20, 12, 0, tzinfo=UTC)
    assert parse_datetime("2024-03-20T08:00:00-04:00") == datetime(2024, 3, 20, 12, 0, tzinfo=UTC)
    # Sans fuseau, la convention interne est l'UTC.
    assert parse_datetime("2024-03-20T12:00:00") == datetime(2024, 3, 20, 12, 0, tzinfo=UTC)
    assert parse_datetime(None) is None
    assert parse_datetime("demain") is None


# ---------------------------------------------------------------------------
# Absence de source
# ---------------------------------------------------------------------------

async def test_without_source_the_engine_says_so(session: AsyncSession) -> None:
    engine = EconomicCalendarEngine()
    report = await engine.refresh(session)

    assert report.configured is False
    assert report.created == 0
    assert report.summary() == NO_SOURCE_MESSAGE

    events, configured = await engine.list_events(session, range_name="today")
    assert events == []
    assert configured is False


async def test_calendar_route_reports_the_missing_configuration(auth_client) -> None:
    response = await auth_client.get("/api/v1/economic-calendar")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["items"] == []
    assert "aucun événement" in body["detail"]

    assert (await auth_client.get("/api/v1/economic-calendar?range=annee")).status_code == 422


# ---------------------------------------------------------------------------
# Synchronisation
# ---------------------------------------------------------------------------

async def test_refresh_creates_then_updates_events(session: AsyncSession) -> None:
    await save_sources(session, [_source()])
    engine = EconomicCalendarEngine(transport=_transport(_payload([_row("cpi", 120)])))

    first = await engine.refresh(session)
    assert (first.created, first.updated) == (1, 0)

    # La publication du chiffre reel met a jour l'evenement existant.
    engine.set_transport(_transport(_payload([_row("cpi", 120, actual="3.2%")])))
    second = await engine.refresh(session)
    assert (second.created, second.updated) == (0, 1)

    stored = await news_repo.list_economic_events(session)
    assert len(stored) == 1
    assert stored[0].actual == "3.2%"
    assert stored[0].forecast == "3.1%"


async def test_rescheduling_resets_the_notification_marks(session: AsyncSession) -> None:
    event, _ = await news_repo.upsert_economic_event(
        session,
        external_id="demo:cpi",
        scheduled_at=NOW + timedelta(minutes=60),
        title="CPI",
        impact=NewsImpact.HIGH,
        currency="USD",
    )
    await news_repo.mark_notified(session, event, [60, 30])
    assert event.notified_minutes == [60, 30]

    moved, created = await news_repo.upsert_economic_event(
        session,
        external_id="demo:cpi",
        scheduled_at=NOW + timedelta(minutes=240),
        title="CPI",
        impact=NewsImpact.HIGH,
        currency="USD",
    )
    assert created is False
    assert moved.notified_minutes == []


async def test_broken_source_is_reported(session: AsyncSession) -> None:
    await save_sources(session, [_source()])
    engine = EconomicCalendarEngine(transport=_transport("pas du json"))
    report = await engine.refresh(session)
    assert report.created == 0
    assert len(report.errors) == 1
    assert "ignorée" in report.summary()


# ---------------------------------------------------------------------------
# Fenetres de consultation
# ---------------------------------------------------------------------------

def test_named_windows_are_expressed_in_utc() -> None:
    engine = EconomicCalendarEngine()
    today_start, today_end = engine.window_for("today", NOW)
    assert today_start == datetime(2024, 3, 20, 0, 0, tzinfo=UTC)
    assert today_end.day == 20 and today_end.hour == 23

    tomorrow_start, _ = engine.window_for("tomorrow", NOW)
    assert tomorrow_start == datetime(2024, 3, 21, 0, 0, tzinfo=UTC)

    week_start, week_end = engine.window_for("week", NOW)
    assert week_start == today_start
    assert (week_end - week_start).days == 6

    # Une fenetre inconnue retombe sur la journee en cours.
    assert engine.window_for("inconnue", NOW) == (today_start, today_end)


async def test_calendar_listing_filters_by_impact_and_currency(session: AsyncSession) -> None:
    await save_sources(session, [_source()])
    body = _payload(
        [
            _row("cpi", 120),
            _row("retail", 180, title="Retail sales", impact="2"),
            _row("ifo", 200, title="IFO", currency="EUR", impact="3"),
        ]
    )
    engine = EconomicCalendarEngine(transport=_transport(body))
    await engine.refresh(session)

    events, configured = await engine.list_events(session, range_name="today", now=NOW)
    assert configured is True
    assert len(events) == 3

    high, _ = await engine.list_events(
        session, range_name="today", impact=NewsImpact.HIGH, now=NOW
    )
    assert {event.title for event in high} == {"CPI y/y", "IFO"}

    usd, _ = await engine.list_events(session, range_name="today", currency="usd", now=NOW)
    assert {event.title for event in usd} == {"CPI y/y", "Retail sales"}


# ---------------------------------------------------------------------------
# Notifications avant evenement (CDC2 section 34)
# ---------------------------------------------------------------------------

async def _seed_event(session: AsyncSession, minutes: int, **overrides):
    defaults = {
        "external_id": "demo:cpi",
        "scheduled_at": NOW + timedelta(minutes=minutes),
        "title": "CPI",
        "impact": NewsImpact.HIGH,
        "currency": "USD",
    }
    defaults.update(overrides)
    event, _ = await news_repo.upsert_economic_event(session, **defaults)
    return event


async def test_reminders_fire_once_per_threshold(session: AsyncSession) -> None:
    session.add(WatchlistItem(canonical="XAUUSD", enabled=True))
    session.add(WatchlistItem(canonical="EURUSD", enabled=True))
    session.add(WatchlistItem(canonical="GBPJPY", enabled=True))
    await _seed_event(session, 60)
    engine = EconomicCalendarEngine()

    # A 58 minutes : le palier 60 se declenche.
    pending = await engine.due_notifications(session, now=NOW + timedelta(minutes=2), publish=False)
    assert len(pending) == 1
    assert pending[0].offset_minutes == 60
    assert pending[0].symbols == ["EURUSD", "XAUUSD"]

    # Immediatement apres, plus rien : jamais deux fois le meme palier.
    assert await engine.due_notifications(session, now=NOW + timedelta(minutes=2), publish=False) == []

    # A 28 minutes : le palier 30.
    pending = await engine.due_notifications(session, now=NOW + timedelta(minutes=32), publish=False)
    assert [item.offset_minutes for item in pending] == [30]

    # A 4 minutes : le palier 5.
    pending = await engine.due_notifications(session, now=NOW + timedelta(minutes=56), publish=False)
    assert [item.offset_minutes for item in pending] == [5]

    stored = await news_repo.economic_event_by_external_id(session, "demo:cpi")
    assert set(stored.notified_minutes) >= {60, 30, 15, 5}


async def test_a_late_start_does_not_replay_every_threshold(session: AsyncSession) -> None:
    """Demarrage a 10 minutes de l'evenement : une seule alerte, pas quatre."""
    await _seed_event(session, 10)
    engine = EconomicCalendarEngine()
    pending = await engine.due_notifications(session, now=NOW, publish=False)
    assert len(pending) == 1
    assert pending[0].offset_minutes == 15
    assert pending[0].minutes_remaining == 10
    assert await engine.due_notifications(session, now=NOW, publish=False) == []


async def test_low_impact_events_do_not_notify(session: AsyncSession) -> None:
    await _seed_event(session, 10, impact=NewsImpact.MEDIUM)
    engine = EconomicCalendarEngine()
    assert await engine.due_notifications(session, now=NOW, publish=False) == []


async def test_past_events_never_notify(session: AsyncSession) -> None:
    await _seed_event(session, -30)
    engine = EconomicCalendarEngine()
    assert await engine.due_notifications(session, now=NOW, publish=False) == []


async def test_notification_threshold_is_configurable(session: AsyncSession) -> None:
    await save_options(
        session, CalendarOptions(notify_offsets=[45], notify_minimum_impact="MEDIUM")
    )
    options = await load_options(session)
    assert options.notify_offsets == [45]

    await _seed_event(session, 40, impact=NewsImpact.MEDIUM)
    engine = EconomicCalendarEngine()
    pending = await engine.due_notifications(session, now=NOW, publish=False)
    assert [item.offset_minutes for item in pending] == [45]


async def test_reminder_message_follows_the_specified_layout(session: AsyncSession) -> None:
    session.add(WatchlistItem(canonical="XAUUSD", enabled=True))
    session.add(WatchlistItem(canonical="EURUSD", enabled=True))
    await _seed_event(session, 30, title="CPI", forecast="3.1%", previous="3.4%")
    engine = EconomicCalendarEngine()
    pending = await engine.due_notifications(session, now=NOW, publish=False)

    body = pending[0].body
    assert pending[0].title == "Événement économique important"
    assert "USD — CPI" in body
    assert "Dans 30 minutes" in body
    assert "Impact : HIGH" in body
    assert "Prévision : 3.1%" in body
    assert "Positions potentiellement concernées :" in body
    assert "XAUUSD" in body and "EURUSD" in body


async def test_message_says_when_no_instrument_is_concerned(session: AsyncSession) -> None:
    await _seed_event(session, 30, currency="NZD")
    engine = EconomicCalendarEngine()
    pending = await engine.due_notifications(session, now=NOW, publish=False)
    assert pending[0].symbols == []
    assert "Aucun instrument suivi" in pending[0].body


# ---------------------------------------------------------------------------
# Lien avec le mode risque news (CDC2 section 35)
# ---------------------------------------------------------------------------

async def test_blackout_uses_the_calendar_from_the_database(session: AsyncSession) -> None:
    await _seed_event(session, 20)
    await save_config(session, BlackoutConfig(minutes_before=30, minutes_after=15))

    blocked, reason = await evaluate_for_session(session, "XAUUSD", NOW)
    assert blocked is True
    assert "CPI" in reason

    blocked, reason = await evaluate_for_session(session, "EURGBP", NOW)
    assert blocked is False and reason is None

    await save_config(session, BlackoutConfig(enabled=False))
    blocked, _ = await evaluate_for_session(session, "XAUUSD", NOW)
    assert blocked is False
