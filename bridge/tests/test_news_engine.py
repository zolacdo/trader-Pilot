"""Tests du moteur d'actualites (CDC2 sections 27 a 30 et 35).

Aucun test n'ouvre de connexion reseau : tous les echanges HTTP passent par un
``httpx.MockTransport`` qui sert des flux RSS et Atom fabriques a la main. Le
service d'intelligence est un double : on choisit s'il repond, s'il rend du
JSON exploitable, ou s'il est absent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.intelligence import (
    AIProviderKind,
    EconomicEvent,
    NewsImpact,
    NewsSentiment,
    WatchlistItem,
)
from app.repositories import news_repo
from app.services.news.engine import NewsEngine
from app.services.news.providers import (
    NewsProviderError,
    NewsSourceProtected,
    RawNewsItem,
    RobotsCache,
    RssNewsProvider,
    build_client,
    parse_feed_date,
)
from app.services.news.relevance import NewsRelevanceEngine
from app.services.news.risk_mode import BlackoutConfig, evaluate_blackout
from app.services.news.sources import NewsOptions, NewsSource, default_sources, save_sources

# ---------------------------------------------------------------------------
# Flux fabriques
# ---------------------------------------------------------------------------

RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Federal Reserve Board - Press Releases</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases.htm</link>
    <description>Communiques officiels</description>
    <item>
      <title>Federal Reserve issues FOMC statement: rate hike of 25 basis points</title>
      <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20240320a.htm</link>
      <description><![CDATA[<p>The Federal Open Market Committee decided to raise the
      target range for the federal funds rate.</p>]]></description>
      <pubDate>Wed, 20 Mar 2024 18:00:00 GMT</pubDate>
      <guid>https://www.federalreserve.gov/newsevents/pressreleases/monetary20240320a.htm</guid>
    </item>
    <item>
      <title>Board announces annual indexing of civil money penalties</title>
      <link>https://www.federalreserve.gov/newsevents/pressreleases/other20240115a.htm</link>
      <description>Routine administrative notice.</description>
      <pubDate>Mon, 15 Jan 2024 14:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Bank of England News</title>
  <updated>2024-03-21T09:00:00Z</updated>
  <entry>
    <title>Bank Rate maintained at 5.25% - March 2024</title>
    <link rel="alternate" href="https://www.bankofengland.co.uk/monetary-policy-summary/2024/march"/>
    <summary>The Monetary Policy Committee voted to maintain Bank Rate.</summary>
    <published>2024-03-21T12:00:00Z</published>
  </entry>
</feed>
"""

FEED_URL = "https://example.test/feed.xml"


def _source(**overrides) -> NewsSource:
    base = {
        "key": "test_feed",
        "name": "Flux de test",
        "url": FEED_URL,
        "official": True,
        "category": "central_bank",
        "countries": ["US"],
        "currencies": ["USD"],
    }
    base.update(overrides)
    return NewsSource(**base)


def _transport(
    *,
    body: str = RSS_FEED,
    status_code: int = 200,
    robots: str | None = None,
    robots_status: int = 404,
) -> httpx.MockTransport:
    """Serveur simule : le flux, et un robots.txt controle par le test."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/robots.txt"):
            if robots is None:
                return httpx.Response(robots_status)
            return httpx.Response(200, text=robots)
        return httpx.Response(status_code, text=body)

    return httpx.MockTransport(handler)


class FakeAI:
    """Double du service d'intelligence hybride.

    ``payload=None`` reproduit le cas ou aucune IA n'est disponible : le vrai
    ``ai_service.complete_json`` retourne alors ``None``.
    """

    def __init__(self, payload: dict | None = None, model: str = "modele-test") -> None:
        self.payload = payload
        self.model = model
        self.calls = 0

    async def complete_json(self, prompt: str, **kwargs):
        self.calls += 1
        if self.payload is None:
            return None
        response = SimpleNamespace(
            payload=self.payload, model=self.model, text="", latency_ms=12
        )
        return SimpleNamespace(
            response=response, provider=AIProviderKind.OPENROUTER, fallback_used=False
        )


# ---------------------------------------------------------------------------
# Lecture des flux
# ---------------------------------------------------------------------------

async def test_rss_feed_is_parsed_into_items() -> None:
    options = NewsOptions(respect_robots=False)
    async with build_client(options, transport=_transport()) as client:
        provider = RssNewsProvider(_source(), options, client=client)
        items = await provider.fetch()

    assert len(items) == 2
    first = items[0]
    assert "FOMC" in first.title
    assert first.url.endswith("monetary20240320a.htm")
    assert first.published_at == datetime(2024, 3, 20, 18, 0, tzinfo=UTC)
    assert first.official is True
    # Le HTML du resume est retire, les espaces normalises.
    assert "<p>" not in first.summary
    assert "federal funds rate" in first.summary


async def test_atom_feed_is_parsed() -> None:
    options = NewsOptions(respect_robots=False)
    async with build_client(options, transport=_transport(body=ATOM_FEED)) as client:
        provider = RssNewsProvider(_source(key="boe"), options, client=client)
        items = await provider.fetch()

    assert len(items) == 1
    assert items[0].title.startswith("Bank Rate maintained")
    assert items[0].url.endswith("/march")
    assert items[0].published_at == datetime(2024, 3, 21, 12, 0, tzinfo=UTC)


def test_feed_dates_are_converted_to_utc() -> None:
    assert parse_feed_date("Wed, 20 Mar 2024 14:00:00 -0400") == datetime(
        2024, 3, 20, 18, 0, tzinfo=UTC
    )
    assert parse_feed_date("2024-03-21T12:00:00Z") == datetime(2024, 3, 21, 12, 0, tzinfo=UTC)
    # Date absente ou illisible : on n'invente pas d'horodatage.
    assert parse_feed_date(None) is None
    assert parse_feed_date("pas une date") is None


async def test_protected_source_is_refused_not_bypassed() -> None:
    options = NewsOptions(respect_robots=False)
    async with build_client(options, transport=_transport(status_code=403)) as client:
        provider = RssNewsProvider(_source(), options, client=client)
        with pytest.raises(NewsSourceProtected) as excinfo:
            await provider.fetch()
    assert "contournement" in str(excinfo.value)


async def test_robots_disallow_stops_the_fetch() -> None:
    options = NewsOptions(respect_robots=True)
    robots = "User-agent: *\nDisallow: /feed.xml\n"
    transport = _transport(robots=robots)
    async with build_client(options, transport=transport) as client:
        provider = RssNewsProvider(_source(), options, client=client, robots=RobotsCache())
        with pytest.raises(NewsProviderError) as excinfo:
            await provider.fetch()
    assert "robots.txt" in str(excinfo.value)


async def test_feed_declaring_entities_is_refused() -> None:
    """Un flux avec DTD est rejete : pas de XXE, pas de billion laughs."""
    hostile = '<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "b">]><rss><channel/></rss>'
    options = NewsOptions(respect_robots=False)
    async with build_client(options, transport=_transport(body=hostile)) as client:
        provider = RssNewsProvider(_source(), options, client=client)
        with pytest.raises(NewsProviderError):
            await provider.fetch()


def test_default_sources_are_public_https_feeds() -> None:
    sources = default_sources()
    assert len(sources) >= 10
    assert all(source.url.startswith("https://") for source in sources)
    # Les sources primaires doivent dominer la liste livree.
    assert sum(1 for source in sources if source.official) >= 6


# ---------------------------------------------------------------------------
# Pertinence
# ---------------------------------------------------------------------------

def _item(title: str, summary: str = "", **overrides) -> RawNewsItem:
    base = {
        "source_key": "test_feed",
        "source_name": "Flux de test",
        "title": title,
        "summary": summary or None,
        "url": f"https://example.test/{abs(hash(title))}",
        "official": True,
    }
    base.update(overrides)
    return RawNewsItem(**base)


def test_prefilter_detects_impact_currencies_and_assets() -> None:
    engine = NewsRelevanceEngine(ai=FakeAI())
    result = engine.prefilter(
        _item("US CPI inflation rises faster than expected in March"),
        watchlist=["XAUUSD", "EURUSD", "US100", "GBPJPY"],
    )
    assert result.impact is NewsImpact.HIGH
    assert "USD" in result.affected_currencies
    assert "XAUUSD" in result.affected_assets
    assert "GBPJPY" not in result.affected_assets
    assert result.category == "inflation"
    assert result.sentiment is NewsSentiment.NEUTRAL


def test_prefilter_keeps_low_impact_with_an_explicit_reason() -> None:
    engine = NewsRelevanceEngine(ai=FakeAI())
    result = engine.prefilter(_item("Board announces annual office relocation"))
    assert result.impact is NewsImpact.LOW
    assert "impact non déterminable" in result.reason


async def test_evaluate_without_ai_keeps_the_deterministic_result() -> None:
    """complete_json renvoie None : le prefiltre doit suffire, sans invention."""
    ai = FakeAI(payload=None)
    engine = NewsRelevanceEngine(ai=ai)
    result = await engine.evaluate(
        _item("FOMC raises rates by 25 basis points"), watchlist=["XAUUSD"]
    )
    assert ai.calls == 1
    assert result.impact is NewsImpact.CRITICAL
    assert result.ai_provider is None
    assert "IA indisponible" in result.reason


async def test_ordinary_news_never_calls_the_ai() -> None:
    ai = FakeAI(payload={"impact": "CRITICAL"})
    engine = NewsRelevanceEngine(ai=ai)
    result = await engine.evaluate(
        _item("Crude oil inventories edge lower this week"), watchlist=["USOIL"]
    )
    assert ai.calls == 0
    assert result.impact is NewsImpact.MEDIUM


async def test_ai_cannot_raise_impact_by_more_than_one_step() -> None:
    ai = FakeAI(payload={"impact": "CRITICAL", "sentiment": "BEARISH", "reason": "marché tendu"})
    engine = NewsRelevanceEngine(ai=ai)
    # La depeche doit concerner un marche suivi, sinon l'IA n'est plus
    # consultee du tout : depuis le 13/09/2026, une depeche sans rattachement
    # marche reste au deterministe (98 % du budget IA y passait).
    result = await engine.evaluate(
        _item("Euro slips against dollar on unclear remarks"), watchlist=["EURUSD"]
    )
    # Le prefiltre voyait MEDIUM : l'IA ne peut pas sauter jusqu'a CRITICAL,
    # elle est ramenee au cran immediatement superieur.
    assert result.impact is NewsImpact.HIGH
    assert result.sentiment is NewsSentiment.BEARISH
    assert result.ai_provider is AIProviderKind.OPENROUTER
    assert "marché tendu" in result.reason


async def test_ai_cannot_invent_a_symbol_outside_the_watchlist() -> None:
    ai = FakeAI(payload={"affectedAssets": ["BTCUSD", "XAUUSD"], "confidence": 0.9})
    engine = NewsRelevanceEngine(ai=ai)
    result = await engine.evaluate(
        _item("Gold hits a record high after inflation data"), watchlist=["XAUUSD"]
    )
    assert result.affected_assets == ["XAUUSD"]


# ---------------------------------------------------------------------------
# Collecte complete
# ---------------------------------------------------------------------------

async def _configure(session: AsyncSession, sources: list[NewsSource]) -> None:
    await save_sources(session, sources)


async def test_refresh_stores_qualified_news(session: AsyncSession) -> None:
    session.add(WatchlistItem(canonical="XAUUSD", enabled=True))
    await _configure(session, [_source()])
    engine = NewsEngine(relevance=NewsRelevanceEngine(ai=FakeAI()), transport=_transport())
    report = await engine.refresh(session)

    assert report.fetched == 2
    assert report.created == 2
    assert report.sources_ok == 1
    assert report.sources_failed == []

    stored = await news_repo.list_news(session)
    assert len(stored) == 2
    fomc = next(event for event in stored if "FOMC" in event.title)
    assert fomc.impact is NewsImpact.CRITICAL
    assert "USD" in fomc.affected_currencies
    assert fomc.source == "Flux de test"
    links = await news_repo.links_for(session, fomc.id)
    assert {link.symbol for link in links} == {"XAUUSD"}


async def test_refresh_skips_already_known_items(session: AsyncSession) -> None:
    await _configure(session, [_source()])
    engine = NewsEngine(relevance=NewsRelevanceEngine(ai=FakeAI()), transport=_transport())
    await engine.refresh(session)
    second = await engine.refresh(session)

    assert second.created == 0
    assert second.already_known == 2


async def test_unreachable_source_is_reported_not_hidden(session: AsyncSession) -> None:
    await _configure(session, [_source(), _source(key="paywall", name="Source protégée")])
    engine = NewsEngine(
        relevance=NewsRelevanceEngine(ai=FakeAI()), transport=_transport(status_code=402)
    )
    report = await engine.refresh(session)

    assert report.created == 0
    assert len(report.sources_failed) == 2
    assert "Source protégée" in report.summary()


async def test_disabled_sources_are_not_fetched(session: AsyncSession) -> None:
    await _configure(session, [_source(enabled=False)])
    engine = NewsEngine(relevance=NewsRelevanceEngine(ai=FakeAI()), transport=_transport())
    report = await engine.refresh(session)
    assert report.fetched == 0
    assert "Aucune source active" in report.summary()


# ---------------------------------------------------------------------------
# Fenetre de silence (CDC2 section 35)
# ---------------------------------------------------------------------------

def _economic(minutes: int, *, currency: str = "USD", impact: NewsImpact = NewsImpact.HIGH):
    now = datetime(2024, 3, 20, 12, 0, tzinfo=UTC)
    return EconomicEvent(
        id=1,
        external_id="test:1",
        scheduled_at=now + timedelta(minutes=minutes),
        title="CPI",
        currency=currency,
        impact=impact,
    )


def test_blackout_window_before_and_after_a_high_impact_event() -> None:
    now = datetime(2024, 3, 20, 12, 0, tzinfo=UTC)
    config = BlackoutConfig(minutes_before=30, minutes_after=15)

    blocked, reason = evaluate_blackout("XAUUSD", [_economic(20)], now, config)
    assert blocked is True
    assert "CPI" in reason

    blocked, reason = evaluate_blackout("XAUUSD", [_economic(-10)], now, config)
    assert blocked is True

    for minutes in (45, -20):
        blocked, reason = evaluate_blackout("XAUUSD", [_economic(minutes)], now, config)
        assert blocked is False and reason is None


def test_blackout_only_applies_to_the_right_currencies_and_levels() -> None:
    now = datetime(2024, 3, 20, 12, 0, tzinfo=UTC)
    config = BlackoutConfig(minutes_before=30, minutes_after=15)

    blocked, _ = evaluate_blackout("EURJPY", [_economic(10, currency="USD")], now, config)
    assert blocked is False

    blocked, _ = evaluate_blackout("EURUSD", [_economic(10, impact=NewsImpact.MEDIUM)], now, config)
    assert blocked is False

    blocked, _ = evaluate_blackout("EURUSD", [_economic(10, currency=None)], now, config)
    assert blocked is False

    disabled = BlackoutConfig(enabled=False)
    blocked, _ = evaluate_blackout("XAUUSD", [_economic(5)], now, disabled)
    assert blocked is False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

async def test_news_routes_require_a_paired_device(client) -> None:
    for path in ("/api/v1/news", "/api/v1/news/sources", "/api/v1/economic-calendar"):
        response = await client.get(path)
        assert response.status_code == 401, path


async def test_news_sources_can_be_read_and_replaced(auth_client) -> None:
    response = await auth_client.get("/api/v1/news/sources")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 10
    assert "paywall" in body["note"]

    payload = {
        "sources": [
            {
                "key": "mine",
                "name": "Mon flux",
                "url": "https://example.test/feed.xml",
                "official": False,
                "currencies": ["eur"],
            }
        ],
        "options": {"respectRobots": False, "similarityThreshold": 0.8},
    }
    response = await auth_client.put("/api/v1/news/sources", json=payload)
    assert response.status_code == 200
    saved = response.json()
    assert saved["count"] == 1
    assert saved["sources"][0]["currencies"] == ["EUR"]
    assert saved["options"]["respectRobots"] is False
    assert saved["options"]["similarityThreshold"] == 0.8

    # La lecture suivante renvoie bien la configuration enregistree.
    response = await auth_client.get("/api/v1/news/sources")
    assert response.json()["sources"][0]["key"] == "mine"


async def test_invalid_source_is_rejected(auth_client) -> None:
    response = await auth_client.put(
        "/api/v1/news/sources",
        json={"sources": [{"key": "bad", "url": "ftp://example.test/feed"}]},
    )
    assert response.status_code == 422
    assert "URL http(s)" in response.json()["detail"]


async def test_news_listing_and_detail_routes(auth_client, monkeypatch) -> None:
    from app.services.news import engine as engine_module

    monkeypatch.setattr(engine_module.news_engine, "_transport", _transport(), raising=False)
    monkeypatch.setattr(
        engine_module.news_engine, "_relevance", NewsRelevanceEngine(ai=FakeAI()), raising=False
    )
    await auth_client.put(
        "/api/v1/news/sources",
        json={
            "sources": [
                {"key": "test_feed", "name": "Flux de test", "url": FEED_URL, "official": True}
            ],
            "options": {"respectRobots": False},
        },
    )

    response = await auth_client.post("/api/v1/news/refresh")
    assert response.status_code == 200
    assert response.json()["created"] == 2

    response = await auth_client.get("/api/v1/news", params={"impact": "CRITICAL"})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    news_id = body["items"][0]["id"]
    assert body["items"][0]["impactLevel"] == "CRITICAL"

    response = await auth_client.get(f"/api/v1/news/{news_id}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["id"] == news_id
    assert detail["confirmedBy"] == []
    assert detail["reason"]

    assert (await auth_client.get("/api/v1/news/999999")).status_code == 404
    assert (await auth_client.get("/api/v1/news", params={"impact": "ENORME"})).status_code == 422


async def test_deux_depeches_identiques_dans_le_meme_tour(session, monkeypatch) -> None:
    """Constate en production : la collecte entiere echouait sur un doublon.

    La session n'est pas rincee entre deux depeches ; une requete ne voyait
    donc pas ce qui venait d'etre ajoute. Deux exemplaires identiques dans la
    meme collecte violaient la contrainte d'unicite et le rafraichissement
    remontait une erreur 500, sans rien enregistrer apres le doublon.
    """
    from app.models.core import utcnow
    from app.services.news.engine import NewsEngine
    from app.services.news.providers import RawNewsItem
    from app.services.news.sources import NewsOptions, NewsSource

    moteur = NewsEngine()
    source = NewsSource(key="doublon", name="Source d'essai", url="https://exemple.test/rss")

    def depeche() -> RawNewsItem:
        return RawNewsItem(
            source_key=source.key,
            source_name=source.name,
            title="La banque centrale maintient ses taux",
            url="https://exemple.test/a",
            summary="Statu quo monetaire.",
            published_at=utcnow(),
            received_at=utcnow(),
            official=True,
        )

    async def fausse_collecte(sources, options):
        # Le meme article, deux fois : cas reel quand un flux republie une
        # entree ou quand deux rubriques partagent un article.
        return [depeche(), depeche()], []

    async def sources_dessai(_session):
        return [source]

    async def options_dessai(_session):
        return NewsOptions()

    monkeypatch.setattr(moteur, "collect", fausse_collecte)
    monkeypatch.setattr("app.services.news.engine.load_sources", sources_dessai)
    monkeypatch.setattr("app.services.news.engine.load_options", options_dessai)

    rapport = await moteur.refresh(session)

    assert rapport.created == 1
    assert rapport.already_known == 1
