"""Tests du moteur de confiance (CDC2 sections 43 et 44).

Deux exigences y sont verifiees sans detour : les poids sont modifiables et
changent reellement le resultat, et une donnee absente n'est jamais remplacee
par une valeur inventee.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction
from app.services.confidence.engine import (
    ComponentScore,
    ConfidenceEngine,
    aligned_score,
)
from app.services.confidence.weights import (
    ConfidenceComponent,
    ConfidenceWeights,
    InvalidWeights,
)


def _toutes_les_composantes(valeur: float) -> list[ComponentScore]:
    return [
        ComponentScore(component=composante, score=valeur, detail="test")
        for composante in ConfidenceComponent
    ]


# ---------------------------------------------------------------------------
# Ponderation
# ---------------------------------------------------------------------------

def test_les_poids_par_defaut_suivent_le_cdc() -> None:
    """CDC2 section 43 : 25/15/10/15/10/10/10/5."""
    poids = ConfidenceWeights()

    assert poids.weight_of(ConfidenceComponent.TECHNICAL) == 0.25
    assert poids.weight_of(ConfidenceComponent.HISTORICAL) == 0.15
    assert poids.weight_of(ConfidenceComponent.MARKET_REGIME) == 0.10
    assert poids.weight_of(ConfidenceComponent.MACRO) == 0.15
    assert poids.weight_of(ConfidenceComponent.NEWS) == 0.10
    assert poids.weight_of(ConfidenceComponent.CROSS_MARKET) == 0.10
    assert poids.weight_of(ConfidenceComponent.TELEGRAM) == 0.10
    assert poids.weight_of(ConfidenceComponent.AI_CONSENSUS) == 0.05
    assert poids.total() == pytest.approx(1.0)


def test_un_poids_negatif_est_refuse() -> None:
    with pytest.raises(InvalidWeights):
        ConfidenceWeights(technical=-0.1)


def test_une_ponderation_entierement_nulle_est_refusee() -> None:
    with pytest.raises(InvalidWeights):
        ConfidenceWeights(
            technical=0,
            historical=0,
            market_regime=0,
            macro=0,
            news=0,
            cross_market=0,
            telegram=0,
            ai_consensus=0,
        )


def test_from_mapping_accepte_les_deux_ecritures() -> None:
    poids = ConfidenceWeights.from_mapping({"TECHNICAL": 0.5, "market_regime": 0.2})

    assert poids.weight_of(ConfidenceComponent.TECHNICAL) == 0.5
    assert poids.weight_of(ConfidenceComponent.MARKET_REGIME) == 0.2
    # Les composantes non citees gardent leur valeur par defaut.
    assert poids.weight_of(ConfidenceComponent.MACRO) == 0.15


def test_une_composante_inconnue_est_refusee() -> None:
    with pytest.raises(InvalidWeights):
        ConfidenceWeights.from_mapping({"astrologie": 1.0})


# ---------------------------------------------------------------------------
# Calcul du score
# ---------------------------------------------------------------------------

def test_toutes_les_composantes_au_maximum_donnent_cent() -> None:
    resultat = ConfidenceEngine().evaluate(_toutes_les_composantes(1.0))

    assert resultat.score == pytest.approx(100.0)
    assert resultat.coverage == pytest.approx(1.0)
    assert resultat.complete is True


def test_toutes_les_composantes_a_zero_donnent_zero() -> None:
    resultat = ConfidenceEngine().evaluate(_toutes_les_composantes(0.0))

    assert resultat.score == pytest.approx(0.0)
    assert resultat.complete is True


def test_le_poids_technique_vaut_bien_vingt_cinq_points() -> None:
    composantes = [ComponentScore(component=composante, score=0.0) for composante in ConfidenceComponent]
    composantes[0] = ComponentScore(component=ConfidenceComponent.TECHNICAL, score=1.0)

    resultat = ConfidenceEngine().evaluate(composantes)

    assert resultat.score == pytest.approx(25.0)


def test_modifier_les_poids_change_le_score() -> None:
    """Exigence explicite du CDC2 : les poids sont configurables et testables."""
    composantes = [ComponentScore(component=composante, score=0.0) for composante in ConfidenceComponent]
    composantes[0] = ComponentScore(component=ConfidenceComponent.TECHNICAL, score=1.0)

    defaut = ConfidenceEngine().evaluate(composantes)
    renforce = ConfidenceEngine(ConfidenceWeights(technical=0.60)).evaluate(composantes)

    assert defaut.score == pytest.approx(25.0)
    assert renforce.score > defaut.score
    assert renforce.score == pytest.approx(60.0 / 1.35 * 1.0, rel=1e-3)


def test_la_somme_des_contributions_egale_le_score() -> None:
    composantes = [
        ComponentScore(component=ConfidenceComponent.TECHNICAL, score=0.9),
        ComponentScore(component=ConfidenceComponent.HISTORICAL, score=0.6),
        ComponentScore(component=ConfidenceComponent.MARKET_REGIME, score=0.7),
        ComponentScore(component=ConfidenceComponent.MACRO, score=0.4),
        ComponentScore(component=ConfidenceComponent.NEWS, score=0.8),
        ComponentScore(component=ConfidenceComponent.CROSS_MARKET, score=0.5),
        ComponentScore(component=ConfidenceComponent.TELEGRAM, score=0.3),
        ComponentScore(component=ConfidenceComponent.AI_CONSENSUS, score=1.0),
    ]

    resultat = ConfidenceEngine().evaluate(composantes)
    total = sum(facteur.contribution for facteur in resultat.factors)

    assert total == pytest.approx(resultat.score, abs=1e-6)


def test_les_scores_hors_bornes_sont_ramenes_dans_zero_un() -> None:
    resultat = ConfidenceEngine().evaluate(
        [
            ComponentScore(component=ConfidenceComponent.TECHNICAL, score=5.0),
            ComponentScore(component=ConfidenceComponent.MACRO, score=-3.0),
        ]
    )

    technique = resultat.factor(ConfidenceComponent.TECHNICAL)
    macro = resultat.factor(ConfidenceComponent.MACRO)
    assert technique is not None and technique.score == pytest.approx(100.0)
    assert macro is not None and macro.score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Donnees absentes
# ---------------------------------------------------------------------------

def test_une_donnee_absente_n_est_jamais_remplacee() -> None:
    """Composante manquante : poids retire, couverture reduite, rien d'invente."""
    composantes = [
        ComponentScore(component=ConfidenceComponent.TECHNICAL, score=1.0),
        ComponentScore(component=ConfidenceComponent.NEWS, score=None),
    ]

    resultat = ConfidenceEngine().evaluate(composantes)

    actualites = resultat.factor(ConfidenceComponent.NEWS)
    assert actualites is not None
    assert actualites.score is None
    assert actualites.weight == 0.0
    assert actualites.contribution == 0.0
    assert ConfidenceComponent.NEWS in resultat.missing
    assert resultat.complete is False
    # Seule la composante technique etait disponible : elle porte tout le score.
    assert resultat.score == pytest.approx(100.0)
    assert resultat.coverage == pytest.approx(0.25)


def test_aucune_composante_disponible_donne_un_score_nul() -> None:
    resultat = ConfidenceEngine().evaluate([])

    assert resultat.score == 0.0
    assert resultat.coverage == 0.0
    assert len(resultat.missing) == len(ConfidenceComponent)
    assert all(facteur.score is None for facteur in resultat.factors)


def test_un_poids_nul_desactive_la_composante() -> None:
    poids = ConfidenceWeights(telegram=0.0)
    resultat = ConfidenceEngine(poids).evaluate(
        [
            ComponentScore(component=ConfidenceComponent.TECHNICAL, score=0.5),
            ComponentScore(component=ConfidenceComponent.TELEGRAM, score=1.0),
        ]
    )

    telegram = resultat.factor(ConfidenceComponent.TELEGRAM)
    assert telegram is not None
    assert telegram.contribution == 0.0
    assert resultat.score == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Explication
# ---------------------------------------------------------------------------

def test_les_facteurs_sont_convertibles_en_lignes_de_journal() -> None:
    resultat = ConfidenceEngine().evaluate(_toutes_les_composantes(0.8))

    lignes = resultat.to_decision_factors(decision_id=42)

    assert len(lignes) == len(ConfidenceComponent)
    assert {ligne.name for ligne in lignes} == {c.value for c in ConfidenceComponent}
    assert all(ligne.decision_id == 42 for ligne in lignes)


def test_les_appuis_et_les_faiblesses_sont_identifies() -> None:
    resultat = ConfidenceEngine().evaluate(
        [
            ComponentScore(component=ConfidenceComponent.TECHNICAL, score=0.95),
            ComponentScore(component=ConfidenceComponent.MACRO, score=0.10),
            ComponentScore(component=ConfidenceComponent.NEWS, score=0.90),
        ]
    )

    appuis = [facteur.component for facteur in resultat.strongest()]
    faiblesses = [facteur.component for facteur in resultat.weakest()]

    assert ConfidenceComponent.TECHNICAL in appuis
    assert ConfidenceComponent.MACRO in faiblesses


# ---------------------------------------------------------------------------
# Alignement directionnel
# ---------------------------------------------------------------------------

def test_une_composante_contraire_devient_une_force_opposee() -> None:
    """Une composante contraire ne depasse jamais le point neutre.

    L'ancienne formule ``1 - note`` faisait d'une conviction NULLE pointant a
    l'oppose un appui MAXIMAL : une lecture technique sans conviction
    annoncant la vente faisait monter le score d'un achat. L'appui d'une
    composante contraire est desormais plafonne a 0,5 et decroit avec sa
    force.
    """
    # Forte conviction contraire : appui quasi nul.
    assert aligned_score(0.9, Direction.SELL, Direction.BUY) == pytest.approx(0.05)
    # Aucune conviction contraire : neutre, jamais un appui.
    assert aligned_score(0.0, Direction.SELL, Direction.BUY) == pytest.approx(0.5)
    # Le cas aligne reste inchange.
    assert aligned_score(0.9, Direction.BUY, Direction.BUY) == pytest.approx(0.9)


def test_une_composante_sans_direction_est_reprise_telle_quelle() -> None:
    assert aligned_score(0.7, None, Direction.BUY) == pytest.approx(0.7)
    assert aligned_score(0.7, Direction.SELL, None) == pytest.approx(0.7)


def test_une_composante_absente_reste_absente_apres_alignement() -> None:
    assert aligned_score(None, Direction.BUY, Direction.BUY) is None
