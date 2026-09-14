"""Les composantes HISTORICAL et MACRO ne remontaient jamais rien.

Mesure du 12/09/2026 sur les decisions autonomes reelles :

    HISTORICAL  « 3 situation(s) comparable(s) seulement : minimum 5 »
    MACRO       « Donnee indisponible »

Deux causes distinctes, et aucune n'etait celle qu'on pouvait supposer.

HISTORICAL cherchait ses analogues sur H1. Le moteur de marche sert au plus
1500 bougies par serie, soit 62 jours en H1 : ce plafond, et non la profondeur
demandee, limitait la recherche. Mesure comparative sur 300 jours :

    instrument   H1    H4
    BTCUSD        3   186
    XAUUSD       58   165
    EURUSD      136   172

MACRO, elle, n'avait jamais ete ecrite : la vue existait dans le contrat, le
moteur de decision la lisait, mais ``build_bundle`` ne passait pas le champ.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.models.enums import Direction
from app.models.intelligence import EconomicEvent, NewsEvent, NewsImpact, NewsSentiment
from app.services.intelligence import assembly

# ---------------------------------------------------------------------------
# HISTORICAL : l'unite de temps de reference
# ---------------------------------------------------------------------------

def test_les_analogues_sont_cherches_en_h4() -> None:
    """H1 ne couvre que 62 jours sous le plafond de 1500 bougies.

    En H4, les memes 1500 bougies couvrent pres de 250 jours -- quatre fois
    plus d'histoire pour exactement le meme cout de chargement.
    """
    assert assembly.ANALOGUES_BASE_TIMEFRAME == "H4"
    assert assembly.pattern_engine.base_timeframe == "H4"


def test_la_profondeur_demandee_reste_raisonnable() -> None:
    """Demander 730 jours faisait echouer le chargement D1 et tuait MT5.

    Le plafond de bougies rend de toute facon une demande plus large inutile.
    """
    assert 120 <= assembly.HISTORIQUE_JOURS <= 400


# ---------------------------------------------------------------------------
# MACRO : la composante qui n'existait pas
# ---------------------------------------------------------------------------

async def test_un_symbole_sans_devise_connue_ne_produit_rien(
    session: AsyncSession,
) -> None:
    """Deviner vaudrait moins que se taire."""
    vue = await assembly.macro_view(session, "INSTRUMENT_INCONNU")

    assert vue.score is None
    assert vue.direction is None
    assert "inconnues" in (vue.detail or "")


async def test_un_calendrier_vide_donne_une_note_pleine(session: AsyncSession) -> None:
    """Aucune publication attendue : le terrain est degage, et cela se mesure."""
    vue = await assembly.macro_view(session, "EURUSD")

    assert vue.score == pytest.approx(1.0)
    assert "Aucune publication majeure" in (vue.detail or "")


async def test_une_publication_critique_imminente_abaisse_la_note(
    session: AsyncSession,
) -> None:
    """Une banque centrale qui parle rend toute conviction fragile."""
    session.add(
        EconomicEvent(
            external_id="fomc-test",
            title="FOMC Statement",
            currency="USD",
            impact=NewsImpact.CRITICAL,
            scheduled_at=utcnow() + timedelta(hours=2),
        )
    )
    await session.flush()

    vue = await assembly.macro_view(session, "EURUSD")

    assert vue.score is not None
    assert vue.score < 0.3, "une publication critique doit peser lourdement"
    assert "FOMC" in (vue.detail or "") or "publication" in (vue.detail or "")


async def test_une_publication_hors_devise_ne_compte_pas(
    session: AsyncSession,
) -> None:
    """Une statistique japonaise ne pese pas sur l'euro-dollar."""
    session.add(
        EconomicEvent(
            external_id="jpy-test",
            title="BoJ Policy Rate",
            currency="JPY",
            impact=NewsImpact.CRITICAL,
            scheduled_at=utcnow() + timedelta(hours=2),
        )
    )
    await session.flush()

    vue = await assembly.macro_view(session, "EURUSD")

    assert vue.score == pytest.approx(1.0)


async def test_une_publication_lointaine_ne_compte_pas(session: AsyncSession) -> None:
    session.add(
        EconomicEvent(
            external_id="lointain-test",
            title="CPI",
            currency="USD",
            impact=NewsImpact.CRITICAL,
            scheduled_at=utcnow() + timedelta(days=5),
        )
    )
    await session.flush()

    vue = await assembly.macro_view(session, "EURUSD")

    assert vue.score == pytest.approx(1.0)


async def _actualite(
    session: AsyncSession, sentiment: NewsSentiment, cle: str
) -> None:
    session.add(
        NewsEvent(
            external_id=cle,
            # Empreinte obligatoire : c'est elle qui identifie une depeche.
            raw_hash=cle,
            title="Actualite macro",
            source="Test",
            impact=NewsImpact.HIGH,
            sentiment=sentiment,
            affected_currencies=["USD"],
            published_at=utcnow() - timedelta(hours=1),
            received_at=utcnow() - timedelta(hours=1),
        )
    )
    await session.flush()


async def test_un_sentiment_net_donne_une_direction(session: AsyncSession) -> None:
    for index in range(3):
        await _actualite(session, NewsSentiment.BULLISH, f"haussiere-{index}")

    vue = await assembly.macro_view(session, "EURUSD")

    assert vue.direction is Direction.BUY


async def test_un_sentiment_partage_ne_donne_aucune_direction(
    session: AsyncSession,
) -> None:
    """En dessous de la marge, le sentiment n'est pas net : se taire vaut mieux."""
    await _actualite(session, NewsSentiment.BULLISH, "h1")
    await _actualite(session, NewsSentiment.BEARISH, "b1")

    vue = await assembly.macro_view(session, "EURUSD")

    assert vue.direction is None


async def test_la_lecture_macro_est_transportee_dans_le_dossier() -> None:
    """Le champ existait deja : c'est ``build_bundle`` qui ne le remplissait pas."""
    import inspect

    source = inspect.getsource(assembly.build_bundle)
    assert "macro=await macro_view(" in source, (
        "la composante macro n'est pas transmise au dossier de decision"
    )
