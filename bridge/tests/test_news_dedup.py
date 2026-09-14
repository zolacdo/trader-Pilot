"""Tests de deduplication et de verification (CDC2 sections 31 et 32).

Aucun acces reseau : les flux sont fabriques dans le test et servis par un
``httpx.MockTransport``.
"""

from __future__ import annotations

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.intelligence import NewsEvent, VerificationStatus
from app.repositories import news_repo
from app.services.news.dedup import (
    NewsDeduplicator,
    raw_hash,
    significant_tokens,
    similarity,
    title_fingerprint,
    verification_for,
)
from app.services.news.engine import NewsEngine
from app.services.news.relevance import NewsRelevanceEngine
from app.services.news.sources import NewsSource, save_sources
from tests.test_news_engine import FakeAI

# Le meme evenement, tel que vingt redactions l'ecriraient.
HEADLINES = [
    "Fed raises interest rates by 25 basis points",
    "Federal Reserve raises interest rates by 25 basis points",
    "FED RAISES INTEREST RATES BY 25 BASIS POINTS",
    "Fed raises interest rates by 25 basis points, citing inflation",
    "The Fed raises its interest rates by 25 basis points",
]

OTHER_HEADLINE = "Oil prices slide as OPEC delays its production decision"


def _feed(entries: list[tuple[str, str]]) -> str:
    """Construit un flux RSS 2.0 a partir de couples (titre, lien)."""
    items = "\n".join(
        f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <description>Dépêche de test.</description>
      <pubDate>Wed, 20 Mar 2024 18:00:00 GMT</pubDate>
    </item>"""
        for title, link in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n  <channel>\n    <title>Flux</title>\n'
        f"{items}\n  </channel>\n</rss>\n"
    )


def _transport(bodies: dict[str, str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/robots.txt"):
            return httpx.Response(404)
        return httpx.Response(200, text=bodies.get(request.url.path, _feed([])))

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Empreintes et similarite
# ---------------------------------------------------------------------------

def test_fingerprint_ignores_case_accents_punctuation_and_word_order() -> None:
    left = title_fingerprint("La BCE relève ses taux, selon un communiqué")
    right = title_fingerprint("Taux releve : la BCE releve ses taux selon communique")
    assert left == right


def test_stopwords_are_dropped_from_the_tokens() -> None:
    tokens = significant_tokens("The Fed raises the interest rates")
    assert "the" not in tokens
    assert {"fed", "raises", "interest", "rates"} <= tokens


def test_similarity_is_high_between_reworded_headlines() -> None:
    assert similarity(HEADLINES[0], HEADLINES[1]) >= 0.72
    assert similarity(HEADLINES[0], OTHER_HEADLINE) < 0.2
    assert similarity(HEADLINES[0], HEADLINES[0]) == 1.0
    # Un titre vide ne ressemble a rien.
    assert similarity("", HEADLINES[0]) == 0.0


def test_raw_hash_distinguishes_sources_and_articles() -> None:
    first = raw_hash("cnbc", "Fed raises rates", "https://a.test/1")
    same = raw_hash("cnbc", "Fed raises rates", "https://a.test/1")
    other_source = raw_hash("reuters", "Fed raises rates", "https://a.test/1")
    other_url = raw_hash("cnbc", "Fed raises rates", "https://a.test/2")
    assert first == same
    assert first != other_source
    assert first != other_url


# ---------------------------------------------------------------------------
# Regroupement
# ---------------------------------------------------------------------------

def _event(event_id: int, title: str, source: str, url: str | None = None) -> NewsEvent:
    return NewsEvent(
        id=event_id,
        raw_hash=raw_hash(source, title, url),
        source=source,
        title=title,
        url=url,
    )


def test_reworded_headline_is_recognised_as_a_duplicate() -> None:
    known = [_event(1, HEADLINES[0], "CNBC", "https://cnbc.test/1")]
    match = NewsDeduplicator().find_duplicate(HEADLINES[1], known, url="https://mw.test/9")
    assert match is not None
    assert match.original.id == 1
    assert match.score >= 0.72
    assert "similaires" in match.reason or "identique" in match.reason


def test_identical_url_is_always_a_duplicate() -> None:
    known = [_event(1, HEADLINES[0], "CNBC", "https://cnbc.test/1")]
    match = NewsDeduplicator().find_duplicate("Un titre sans rapport", known, url="https://cnbc.test/1")
    assert match is not None
    assert match.reason == "adresse identique"


def test_unrelated_headline_is_not_grouped() -> None:
    known = [_event(1, HEADLINES[0], "CNBC", "https://cnbc.test/1")]
    assert NewsDeduplicator().find_duplicate(OTHER_HEADLINE, known, url="https://x.test/1") is None


def test_duplicates_never_chain_to_another_duplicate() -> None:
    """Une reprise pointe toujours vers l'original, jamais vers une reprise."""
    original = _event(1, HEADLINES[0], "CNBC", "https://cnbc.test/1")
    copy = _event(2, HEADLINES[1], "MarketWatch", "https://mw.test/2")
    copy.duplicate_of = 1
    match = NewsDeduplicator().find_duplicate(HEADLINES[2], [copy, original], url="https://y.test/3")
    assert match is not None
    assert match.original.id == 1


# ---------------------------------------------------------------------------
# Verification (CDC2 section 32)
# ---------------------------------------------------------------------------

def test_verification_depends_on_the_number_of_independent_sources() -> None:
    assert verification_for({"CNBC"}) is VerificationStatus.UNCONFIRMED
    assert verification_for({"CNBC", "MarketWatch"}) is VerificationStatus.PARTIALLY_CONFIRMED
    assert (
        verification_for({"CNBC", "MarketWatch", "Yahoo"}) is VerificationStatus.CONFIRMED
    )


def test_a_primary_source_counts_more_than_a_relay() -> None:
    # Seule, l'institution qui publie vaut deja une confirmation partielle.
    assert (
        verification_for({"Federal Reserve"}, official_sources={"Federal Reserve"})
        is VerificationStatus.PARTIALLY_CONFIRMED
    )
    # Avec un relais, l'information est confirmee.
    assert (
        verification_for({"Federal Reserve", "CNBC"}, official_sources={"Federal Reserve"})
        is VerificationStatus.CONFIRMED
    )


# ---------------------------------------------------------------------------
# Integration : la meme information reprise par plusieurs medias
# ---------------------------------------------------------------------------

async def test_same_story_from_many_media_becomes_one_news_with_confirmations(
    session: AsyncSession,
) -> None:
    bodies = {
        f"/media{index}.xml": _feed([(headline, f"https://media{index}.test/article")])
        for index, headline in enumerate(HEADLINES)
    }
    sources = [
        NewsSource(
            key=f"media{index}",
            name=f"Média {index}",
            url=f"https://media{index}.test/media{index}.xml",
        )
        for index in range(len(HEADLINES))
    ]
    await save_sources(session, sources)

    engine = NewsEngine(
        relevance=NewsRelevanceEngine(ai=FakeAI()),
        transport=_transport(bodies),
    )
    report = await engine.refresh(session)

    assert report.fetched == len(HEADLINES)
    assert report.created == 1
    assert report.duplicates == len(HEADLINES) - 1

    visible = await news_repo.list_news(session)
    assert len(visible) == 1
    original = visible[0]
    assert original.confirmations == len(HEADLINES)
    assert original.verification is VerificationStatus.CONFIRMED

    copies = await news_repo.duplicates_of(session, original.id)
    assert len(copies) == len(HEADLINES) - 1
    assert all(copy.duplicate_of == original.id for copy in copies)

    # Les reprises restent consultables si on les demande explicitement.
    everything = await news_repo.list_news(session, include_duplicates=True)
    assert len(everything) == len(HEADLINES)


async def test_two_different_stories_stay_separate(session: AsyncSession) -> None:
    bodies = {
        "/feed.xml": _feed(
            [
                (HEADLINES[0], "https://a.test/1"),
                (OTHER_HEADLINE, "https://a.test/2"),
            ]
        )
    }
    await save_sources(
        session, [NewsSource(key="a", name="Média A", url="https://a.test/feed.xml")]
    )
    engine = NewsEngine(
        relevance=NewsRelevanceEngine(ai=FakeAI()), transport=_transport(bodies)
    )
    report = await engine.refresh(session)

    assert report.created == 2
    assert report.duplicates == 0
    stored = await news_repo.list_news(session)
    assert {event.confirmations for event in stored} == {1}
    assert all(event.verification is VerificationStatus.UNCONFIRMED for event in stored)


async def test_confirmation_status_rises_with_each_new_source(session: AsyncSession) -> None:
    await save_sources(
        session, [NewsSource(key="m0", name="Média 0", url="https://m0.test/f.xml")]
    )
    engine = NewsEngine(
        relevance=NewsRelevanceEngine(ai=FakeAI()),
        transport=_transport({"/f.xml": _feed([(HEADLINES[0], "https://m0.test/1")])}),
    )
    await engine.refresh(session)
    first = (await news_repo.list_news(session))[0]
    assert first.verification is VerificationStatus.UNCONFIRMED

    await save_sources(
        session,
        [
            NewsSource(key="m0", name="Média 0", url="https://m0.test/f.xml"),
            NewsSource(key="m1", name="Média 1", url="https://m1.test/g.xml"),
        ],
    )
    engine.set_transport(
        _transport(
            {
                "/f.xml": _feed([(HEADLINES[0], "https://m0.test/1")]),
                "/g.xml": _feed([(HEADLINES[1], "https://m1.test/1")]),
            }
        )
    )
    await engine.refresh(session)
    updated = await news_repo.get_news(session, first.id)
    assert updated.confirmations == 2
    assert updated.verification is VerificationStatus.PARTIALLY_CONFIRMED


def test_une_guerre_des_prix_n_est_pas_un_evenement_geopolitique() -> None:
    """Constaté en production : « price war » classait un article sur un
    téléphone pliable en impact critique, ce qui bloquait le trading.

    Le vocabulaire exige désormais un qualificatif : « war in », « at war ».
    """
    from app.services.news.taxonomy import (
        CATEGORY_KEYWORDS,
        CRITICAL_KEYWORDS,
        find_keywords,
        normalize,
    )

    commercial = normalize(
        "Want Apple foldable iPhone? Here is what T-Mobile, AT&T and Verizon "
        "are doing in their price war to lower the cost."
    )
    assert find_keywords(commercial, CRITICAL_KEYWORDS) == []
    assert find_keywords(commercial, CATEGORY_KEYWORDS["geopolitics"]) == []

    # Un evenement geopolitique reel reste detecte.
    geopolitique = normalize("Escalation of the war in the region halts oil exports")
    assert find_keywords(geopolitique, CRITICAL_KEYWORDS)


def test_un_commentaire_sur_les_taux_n_est_pas_critique() -> None:
    """Constaté en production : « rate hike » classait en impact critique tout
    commentaire sur les *probabilités* de hausse.

    Le garde-fou d'actualité se déclenchait alors en permanence et le système
    ne prenait plus aucune position. Ces dépêches restent en impact élevé :
    l'information n'est pas perdue, elle n'est simplement plus bloquante.
    """
    from app.services.news.taxonomy import (
        CRITICAL_KEYWORDS,
        HIGH_KEYWORDS,
        find_keywords,
        normalize,
    )

    commentaire = normalize(
        "September Fed decision is now a coin flip as rate hike odds increase"
    )
    assert find_keywords(commentaire, CRITICAL_KEYWORDS) == []
    assert "rate hike" in find_keywords(commentaire, HIGH_KEYWORDS)

    # Une decision effectivement prise reste critique.
    decision = normalize("The Federal Reserve raises rates by 25 basis points")
    assert find_keywords(decision, CRITICAL_KEYWORDS)
