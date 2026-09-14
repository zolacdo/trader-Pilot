"""Tests du consensus entre les deux modeles interroges (CDC2 sections 11 a 13, 105, 106).

Regle centrale verifiee ici : on ne fait jamais la moyenne entre un BUY et un
SELL. Un desaccord bloque l'automatisme.
"""

from __future__ import annotations

from app.models.enums import Direction
from app.models.intelligence import AIProviderKind, ConsensusOutcome
from app.services.ai.ensemble.service import (
    AIConsensusEngine,
    ProviderOpinion,
)


def _avis(
    modele: str,
    direction: Direction | None,
    confidence: float,
    *,
    valid: bool = True,
) -> ProviderOpinion:
    """Deux avis ne different plus que par le MODELE interroge.

    Le fournisseur est OpenRouter dans les deux cas depuis le retrait de l'IA
    locale : ce qui fonde la confrontation, c'est la diversite des modeles.
    """
    return ProviderOpinion(
        provider=AIProviderKind.OPENROUTER,
        model=modele,
        direction=direction,
        confidence=confidence,
        summary="analyse",
        latency_ms=50,
        valid=valid,
    )


# ---------------------------------------------------------------------------
# Accord et desaccord
# ---------------------------------------------------------------------------

def test_deux_moteurs_d_accord_donnent_un_consensus() -> None:
    """CDC2 section 106 : modele principal BUY + OpenRouter BUY."""
    resultat = AIConsensusEngine.evaluate(
        [
            _avis("modele-principal", Direction.BUY, 0.78),
            _avis("modele-second", Direction.BUY, 0.82),
        ]
    )

    assert resultat.outcome is ConsensusOutcome.CONSENSUS
    assert resultat.direction is Direction.BUY
    assert 0.79 <= resultat.confidence <= 0.81
    assert resultat.blocks_auto_trade is False


def test_desaccord_bloque_l_automatisme() -> None:
    """CDC2 section 105 : modele principal BUY, OpenRouter SELL."""
    resultat = AIConsensusEngine.evaluate(
        [
            _avis("modele-principal", Direction.BUY, 0.90),
            _avis("modele-second", Direction.SELL, 0.85),
        ]
    )

    assert resultat.outcome is ConsensusOutcome.DISAGREEMENT
    # Aucune direction retenue : surtout pas une moyenne entre BUY et SELL.
    assert resultat.direction is None
    assert resultat.blocks_auto_trade is True


def test_meme_direction_mais_convictions_eloignees() -> None:
    resultat = AIConsensusEngine.evaluate(
        [
            _avis("modele-principal", Direction.BUY, 0.95),
            _avis("modele-second", Direction.BUY, 0.40),
        ]
    )

    assert resultat.outcome is ConsensusOutcome.PARTIAL_CONSENSUS
    assert resultat.direction is Direction.BUY
    # La plus prudente des deux est retenue, jamais la plus optimiste.
    assert resultat.confidence == 0.40


def test_un_seul_moteur_ne_vaut_pas_un_consensus() -> None:
    resultat = AIConsensusEngine.evaluate(
        [
            _avis("modele-principal", Direction.BUY, 0.95),
            _avis("modele-second", None, 0.0, valid=False),
        ]
    )

    assert resultat.outcome is ConsensusOutcome.INSUFFICIENT_DATA
    assert resultat.confidence <= 0.6
    assert resultat.blocks_auto_trade is True


def test_aucun_moteur_disponible() -> None:
    resultat = AIConsensusEngine.evaluate([])
    assert resultat.outcome is ConsensusOutcome.PROVIDER_UNAVAILABLE
    assert resultat.blocks_auto_trade is True


def test_sorties_illisibles_ne_produisent_aucune_direction() -> None:
    resultat = AIConsensusEngine.evaluate(
        [
            _avis("modele-principal", None, 0.0, valid=False),
            _avis("modele-second", None, 0.0, valid=False),
        ]
    )
    assert resultat.outcome is ConsensusOutcome.INSUFFICIENT_DATA
    assert resultat.direction is None


# ---------------------------------------------------------------------------
# Recalibrage sur les mesures deterministes (CDC2 section 13)
# ---------------------------------------------------------------------------

def test_contradiction_technique_fait_chuter_la_confiance() -> None:
    """Une confiance annoncee ne vaut rien contre les donnees mesurees."""
    resultat = AIConsensusEngine.evaluate(
        [
            _avis("modele-principal", Direction.BUY, 0.90),
            _avis("modele-second", Direction.BUY, 0.92),
        ]
    )
    assert resultat.outcome is ConsensusOutcome.CONSENSUS

    recalibre = AIConsensusEngine.recalibrate(resultat, Direction.SELL, 0.8)

    assert recalibre.confidence <= 0.55
    assert recalibre.outcome is ConsensusOutcome.PARTIAL_CONSENSUS
    assert "technique" in recalibre.detail.lower()


def test_accord_avec_la_technique_donne_une_petite_prime() -> None:
    resultat = AIConsensusEngine.evaluate(
        [
            _avis("modele-principal", Direction.BUY, 0.70),
            _avis("modele-second", Direction.BUY, 0.72),
        ]
    )
    avant = resultat.confidence

    recalibre = AIConsensusEngine.recalibrate(resultat, Direction.BUY, 0.85)

    assert recalibre.confidence > avant
    assert recalibre.confidence <= 0.95


def test_le_recalibrage_ne_cree_jamais_de_direction() -> None:
    resultat = AIConsensusEngine.evaluate(
        [
            _avis("modele-principal", Direction.BUY, 0.8),
            _avis("modele-second", Direction.SELL, 0.8),
        ]
    )
    recalibre = AIConsensusEngine.recalibrate(resultat, Direction.BUY, 0.9)

    assert recalibre.direction is None
    assert recalibre.outcome is ConsensusOutcome.DISAGREEMENT
