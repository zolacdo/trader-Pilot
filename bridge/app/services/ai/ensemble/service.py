"""Mode ENSEMBLE et moteur de consensus (CDC2 sections 11, 12, 13).

Les deux intelligences analysent la meme question separement, puis leurs
sorties sont confrontees. Regle non negociable : on ne fait JAMAIS la moyenne
entre un BUY et un SELL. Un desaccord sur une decision financiere conduit a
NO_TRADE ou a une revue manuelle, jamais a un compromis invente.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.config.logging_config import get_logger
from app.models.enums import Direction
from app.models.intelligence import (
    AIMode,
    AIProviderKind,
    AISettings,
    AITaskKind,
    ConsensusOutcome,
)
from app.services.ai.base import AIProviderError, AIResponse
from app.services.ai.router.router import AIRouter

logger = get_logger(__name__)

# Ecart de confiance au-dela duquel un accord de direction reste partiel.
PARTIAL_CONSENSUS_GAP = 0.30


@dataclass(slots=True)
class ProviderOpinion:
    """Avis structure d'un moteur, deja valide."""

    provider: AIProviderKind
    model: str
    direction: Direction | None
    confidence: float
    summary: str
    latency_ms: int
    valid: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "model": self.model,
            "direction": self.direction.value if self.direction else None,
            "confidence": round(self.confidence, 3),
            "summary": self.summary[:500],
            "latencyMs": self.latency_ms,
            "valid": self.valid,
            "error": self.error,
        }


@dataclass(slots=True)
class ConsensusResult:
    """Verdict de la confrontation."""

    outcome: ConsensusOutcome
    direction: Direction | None = None
    confidence: float = 0.0
    detail: str = ""
    opinions: list[ProviderOpinion] = field(default_factory=list)

    @property
    def agrees(self) -> bool:
        return self.outcome is ConsensusOutcome.CONSENSUS

    @property
    def blocks_auto_trade(self) -> bool:
        """Un desaccord ou une indisponibilite interdit l'automatisme."""
        return self.outcome in {
            ConsensusOutcome.DISAGREEMENT,
            ConsensusOutcome.INSUFFICIENT_DATA,
            ConsensusOutcome.PROVIDER_UNAVAILABLE,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "direction": self.direction.value if self.direction else None,
            "confidence": round(self.confidence, 3),
            "detail": self.detail,
            "opinions": [opinion.to_dict() for opinion in self.opinions],
        }


def _read_direction(payload: dict[str, Any] | None) -> Direction | None:
    """Direction lue dans la sortie du modele, sans interpretation libre."""
    if not payload:
        return None
    raw = payload.get("direction") or payload.get("action") or payload.get("signal")
    if not isinstance(raw, str):
        return None
    value = raw.strip().upper()
    if value in {"BUY", "LONG", "STRONG_BUY"}:
        return Direction.BUY
    if value in {"SELL", "SHORT", "STRONG_SELL"}:
        return Direction.SELL
    return None


def _read_confidence(payload: dict[str, Any] | None) -> float:
    if not payload:
        return 0.0
    raw = payload.get("confidence")
    if isinstance(raw, (int, float)):
        value = float(raw)
        # Les modeles renvoient tantot 0-1, tantot 0-100.
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))
    return 0.0


def _read_summary(payload: dict[str, Any] | None, fallback: str) -> str:
    if payload:
        for key in ("summary", "reason", "explanation", "analysis"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback.strip()[:500]


def opinion_from_response(response: AIResponse) -> ProviderOpinion:
    return ProviderOpinion(
        provider=response.provider,
        model=response.model,
        direction=_read_direction(response.payload),
        confidence=_read_confidence(response.payload),
        summary=_read_summary(response.payload, response.text),
        latency_ms=response.latency_ms,
        valid=response.valid_json,
    )


class AIConsensusEngine:
    """Confronte les avis et recalibre la confiance (CDC2 sections 12 et 13)."""

    @staticmethod
    def evaluate(opinions: list[ProviderOpinion]) -> ConsensusResult:
        usable = [o for o in opinions if o.valid and o.direction is not None]

        if not opinions:
            return ConsensusResult(
                ConsensusOutcome.PROVIDER_UNAVAILABLE,
                detail="Aucun moteur n'a repondu.",
                opinions=opinions,
            )
        if not usable:
            return ConsensusResult(
                ConsensusOutcome.INSUFFICIENT_DATA,
                detail="Aucune direction exploitable n'a ete produite.",
                opinions=opinions,
            )
        if len(usable) == 1:
            single = usable[0]
            return ConsensusResult(
                ConsensusOutcome.INSUFFICIENT_DATA,
                direction=single.direction,
                # Un seul avis ne vaut pas un consensus : la confiance est bridee.
                confidence=min(single.confidence, 0.6),
                detail=f"Un seul moteur a repondu ({single.provider.value}).",
                opinions=opinions,
            )

        directions = {opinion.direction for opinion in usable}
        if len(directions) > 1:
            return ConsensusResult(
                ConsensusOutcome.DISAGREEMENT,
                detail=" contre ".join(
                    f"{o.provider.value}={o.direction.value if o.direction else '?'}" for o in usable
                ),
                opinions=opinions,
            )

        direction = usable[0].direction
        confidences = [opinion.confidence for opinion in usable]
        gap = max(confidences) - min(confidences)
        mean = sum(confidences) / len(confidences)

        if gap > PARTIAL_CONSENSUS_GAP:
            return ConsensusResult(
                ConsensusOutcome.PARTIAL_CONSENSUS,
                direction=direction,
                # Meme direction mais convictions eloignees : on retient la plus prudente.
                confidence=min(confidences),
                detail=f"Meme direction, ecart de confiance de {gap:.0%}.",
                opinions=opinions,
            )

        return ConsensusResult(
            ConsensusOutcome.CONSENSUS,
            direction=direction,
            confidence=mean,
            detail=f"Accord des {len(usable)} moteurs.",
            opinions=opinions,
        )

    @staticmethod
    def recalibrate(
        result: ConsensusResult,
        deterministic_direction: Direction | None,
        deterministic_score: float | None,
    ) -> ConsensusResult:
        """Confronte l'avis des modeles aux mesures deterministes.

        Une confiance annoncee a 90 % qui contredit l'analyse technique ne vaut
        pas 90 % (CDC2 section 13). Les donnees mesurees ont le dernier mot.
        """
        if result.direction is None or deterministic_direction is None:
            return result

        if deterministic_direction is not result.direction:
            result.confidence = min(result.confidence, 0.55)
            result.detail = (
                f"{result.detail} Contradiction avec l'analyse technique "
                f"({deterministic_direction.value})."
            ).strip()
            if result.outcome is ConsensusOutcome.CONSENSUS:
                result.outcome = ConsensusOutcome.PARTIAL_CONSENSUS
            return result

        if deterministic_score is not None and deterministic_score >= 0.7:
            # Accord modeles + mesures : legere prime, jamais au-dela de 0.95.
            result.confidence = min(0.95, result.confidence + 0.05)
        return result


class AIEnsembleService:
    """Confronte deux modeles OpenRouter puis passe au consensus."""

    def __init__(self, router: AIRouter) -> None:
        self._router = router

    async def analyse(
        self,
        settings: AISettings,
        prompt: str,
        *,
        system: str | None = None,
        task: AITaskKind = AITaskKind.OPPORTUNITY_REVIEW,
        max_tokens: int = 700,
        timeout: float | None = None,
    ) -> ConsensusResult:
        """Confronte deux avis sur la meme question.

        Deux avis se distinguent d'abord par le FOURNISSEUR quand plusieurs
        sont configures : leurs quotas et leurs modes de panne sont alors
        independants, ce qui rend un desaccord informatif plutot
        qu'accidentel. A defaut, on se rabat sur deux modeles du meme
        fournisseur.

        Quand un seul avis est possible, on ne fait PAS semblant d'avoir une
        confrontation : le moteur de consensus renvoie INSUFFICIENT_DATA avec
        une confiance bridee, ce qui est exactement ce qu'un avis unique vaut.
        """
        disponibles = self._router.available_kinds(settings)
        if not disponibles:
            return ConsensusResult(
                ConsensusOutcome.PROVIDER_UNAVAILABLE,
                detail="Aucun moteur d'intelligence configure et actif.",
            )

        # (fournisseur, modele) ; ``None`` = le modele par defaut du moteur.
        demandes: list[tuple[AIProviderKind, str | None]] = [(disponibles[0], None)]
        if settings.mode is AIMode.ENSEMBLE:
            if len(disponibles) > 1:
                demandes.append((disponibles[1], None))
            else:
                second = (settings.ensemble_secondary_model or "").strip()
                if second:
                    demandes.append((disponibles[0], second))

        async def ask(cible: tuple[AIProviderKind, str | None]) -> ProviderOpinion:
            kind, modele = cible
            provider = self._router.provider(kind)
            try:
                response = await provider.complete_json(
                    prompt,
                    system=system,
                    task=task,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    model=modele,
                )
            except AIProviderError as exc:
                return ProviderOpinion(
                    provider=kind,
                    model=modele or "",
                    direction=None,
                    confidence=0.0,
                    summary="",
                    latency_ms=0,
                    valid=False,
                    error=str(exc)[:200],
                )
            return opinion_from_response(response)

        opinions = list(await asyncio.gather(*(ask(cible) for cible in demandes)))
        result = AIConsensusEngine.evaluate(opinions)
        logger.info(
            "Consensus IA (%s) : %s — %s", task.value, result.outcome.value, result.detail
        )
        return result
