"""Les dépêches sans portée marché s'effacent seules ; les autres restent.

Le flux sature : 306 dépêches relues à chaque tour, dont la grande majorité
sans le moindre rapport avec le portefeuille. Mais effacer trop serait bien
pire qu'effacer trop peu — une dépêche perdue ne revient pas, et c'est elle
qui alimente le sentiment du score.

La règle retenue : on n'efface qu'en cas d'insignifiance **cumulée** — impact
faible, tonalité neutre, ET aucun instrument rattaché. Un seul de ces trois
signes qui manque suffit à conserver la dépêche.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.models.intelligence import (
    NewsAssetLink,
    NewsEvent,
    NewsImpact,
    NewsSentiment,
)
from app.repositories import news_repo


async def _depeche(
    session: AsyncSession,
    *,
    titre: str,
    age_minutes: int,
    impact: NewsImpact = NewsImpact.LOW,
    sentiment: NewsSentiment = NewsSentiment.NEUTRAL,
    symbole: str | None = None,
) -> NewsEvent:
    evenement = NewsEvent(
        raw_hash=f"hash-{titre}",
        source="Flux de test",
        title=titre,
        url=f"https://example.test/{abs(hash(titre))}",
        published_at=utcnow() - timedelta(minutes=age_minutes),
        received_at=utcnow() - timedelta(minutes=age_minutes),
        impact=impact,
        sentiment=sentiment,
    )
    session.add(evenement)
    await session.flush()
    if symbole is not None and evenement.id is not None:
        session.add(NewsAssetLink(news_id=evenement.id, symbol=symbole))
        await session.flush()
    return evenement


def _limite(heures: int = 1):
    return utcnow() - timedelta(hours=heures)


class TestCeQuiEstEfface:
    async def test_une_depeche_insignifiante_et_ancienne_part(
        self, session: AsyncSession
    ) -> None:
        await _depeche(session, titre="Bulletin quotidien sans objet", age_minutes=90)

        assert await news_repo.purge_unimportant(session, _limite()) == 1

    async def test_plusieurs_depeches_partent_dans_le_meme_tour(
        self, session: AsyncSession
    ) -> None:
        for index in range(4):
            await _depeche(session, titre=f"Bruit {index}", age_minutes=120)

        assert await news_repo.purge_unimportant(session, _limite()) == 4


class TestCeQuiEstConserve:
    """Chacun de ces tests protege une raison de garder une depeche."""

    async def test_une_depeche_recente_reste(self, session: AsyncSession) -> None:
        """Une heure n'est pas encore passee : elle peut encore servir."""
        await _depeche(session, titre="Bulletin de ce matin", age_minutes=20)

        assert await news_repo.purge_unimportant(session, _limite()) == 0

    async def test_un_impact_eleve_protege_la_depeche(
        self, session: AsyncSession
    ) -> None:
        await _depeche(
            session,
            titre="Decision de taux de la Fed",
            age_minutes=300,
            impact=NewsImpact.HIGH,
        )

        assert await news_repo.purge_unimportant(session, _limite()) == 0

    async def test_une_tonalite_marquee_protege_la_depeche(
        self, session: AsyncSession
    ) -> None:
        """Une dépêche orientée nourrit le sentiment, même a impact faible."""
        await _depeche(
            session,
            titre="Le marche recule nettement",
            age_minutes=300,
            sentiment=NewsSentiment.BEARISH,
        )

        assert await news_repo.purge_unimportant(session, _limite()) == 0

    async def test_un_rattachement_marche_protege_la_depeche(
        self, session: AsyncSession
    ) -> None:
        """C'est la protection qui compte le plus : elle concerne un instrument."""
        await _depeche(
            session,
            titre="Note discrete sur l'or",
            age_minutes=300,
            symbole="XAUUSD",
        )

        assert await news_repo.purge_unimportant(session, _limite()) == 0


class TestTriFin:
    async def test_seules_les_insignifiantes_partent_dans_un_lot_mixte(
        self, session: AsyncSession
    ) -> None:
        """Le cas reel : du bruit et de l'utile dans le meme flux."""
        await _depeche(session, titre="Bruit A", age_minutes=200)
        await _depeche(session, titre="Bruit B", age_minutes=200)
        await _depeche(session, titre="Or en hausse", age_minutes=200, symbole="XAUUSD")
        await _depeche(
            session, titre="Fed", age_minutes=200, impact=NewsImpact.CRITICAL
        )
        await _depeche(session, titre="Trop recente", age_minutes=10)

        efface = await news_repo.purge_unimportant(session, _limite())

        assert efface == 2
        restantes = {e.title for e in await news_repo.recent_news(session, _limite(24))}
        assert "Or en hausse" in restantes
        assert "Fed" in restantes
        assert "Trop recente" in restantes
        assert "Bruit A" not in restantes
        assert "Bruit B" not in restantes

    async def test_un_flux_vide_ne_leve_pas(self, session: AsyncSession) -> None:
        assert await news_repo.purge_unimportant(session, _limite()) == 0
