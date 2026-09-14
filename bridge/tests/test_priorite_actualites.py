"""Une alerte d'actualite ne crie pas plus fort que l'actualite ne pese.

Constate en production le 12/09/2026 : 78 alertes en dix-huit heures, TOUTES
en priorite HIGH, alors que l'ecran affichait « Impact faible » sur chacune.
Le gabarit recevait bien l'impact mesure, puis le rangeait dans `data` sans
jamais s'en servir : la priorite etait ecrite en dur.

Le reglage « priorite minimale : HIGH » ne filtrait donc rien. Ces tests
verrouillent la correspondance qui lui rend son sens.
"""

from __future__ import annotations

import pytest

from app.models.intelligence import NewsImpact, NotificationPriority
from app.services.notifications import templates


@pytest.mark.parametrize(
    ("impact", "attendue"),
    [
        (NewsImpact.CRITICAL, NotificationPriority.CRITICAL),
        (NewsImpact.HIGH, NotificationPriority.HIGH),
        (NewsImpact.MEDIUM, NotificationPriority.MEDIUM),
        (NewsImpact.LOW, NotificationPriority.LOW),
    ],
)
def test_la_priorite_suit_l_impact(
    impact: NewsImpact, attendue: NotificationPriority
) -> None:
    assert templates.priority_for_impact(impact) is attendue


@pytest.mark.parametrize("brut", ["low", " HIGH ", "critical"])
def test_l_impact_est_lu_quelle_que_soit_sa_casse(brut: str) -> None:
    """Les sources ecrivent l'impact de toutes les facons."""
    assert templates.priority_for_impact(brut) is not NotificationPriority.MEDIUM


@pytest.mark.parametrize("inconnu", [None, "", "PEUT-ETRE", 42])
def test_un_impact_inconnu_reste_au_milieu(inconnu: object) -> None:
    """Ni assez sur pour reveiller quelqu'un, ni assez anodin pour etre tu."""
    assert templates.priority_for_impact(inconnu) is NotificationPriority.MEDIUM


def test_une_depeche_a_impact_faible_ne_produit_pas_une_alerte_haute() -> None:
    """Le cas exact vu en production."""
    brouillon = templates.high_impact_news(
        headline="DocuSign director sells $3.0 million in stock",
        affected=[],
        interpretation="Vente d'initie sans effet sur les devises suivies.",
        source="Investing.com",
        published_at=None,
        impact=NewsImpact.LOW,
    )

    assert brouillon.priority is NotificationPriority.LOW, (
        "une vente d'initie declenchait une alerte de priorite haute"
    )


def test_une_actualite_critique_garde_toute_sa_force() -> None:
    """Le resserrage ne doit pas etouffer ce qui compte vraiment."""
    brouillon = templates.high_impact_news(
        headline="US consumer prices accelerate in August",
        affected=["XAUUSD", "EURUSD"],
        interpretation="Inflation au-dessus du consensus.",
        source="Reuters",
        published_at=None,
        impact=NewsImpact.CRITICAL,
    )

    assert brouillon.priority is NotificationPriority.CRITICAL
    assert brouillon.symbol == "XAUUSD"


def test_l_impact_reste_lisible_dans_les_donnees() -> None:
    """La priorite derive de l'impact, mais l'impact reste consultable."""
    brouillon = templates.high_impact_news(
        headline="Titre",
        affected=[],
        interpretation=None,
        source="Source",
        published_at=None,
        impact=NewsImpact.MEDIUM,
    )

    assert brouillon.data["impact"] == "MEDIUM"
