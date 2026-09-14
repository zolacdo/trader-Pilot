"""Mise en mots d'une opportunite par les modeles (CDC2 section 41).

Les intelligences n'ont ici qu'un role : interpreter, contextualiser,
expliquer. Le prompt leur donne les niveaux deja calcules et leur interdit
explicitement d'en proposer d'autres. Surtout, le code ne relit jamais un prix
dans leur reponse : seul le texte d'explication est conserve.

C'est structurel, pas declaratif : meme si un modele renvoyait des prix
inventes, ils n'auraient aucun chemin pour atteindre ``OpportunityDraft``.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.config.logging_config import get_logger
from app.models.intelligence import AITaskKind
from app.services.decision.inputs import ConsensusView
from app.services.opportunities.generator import OpportunityDraft

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "Tu commentes un plan de trade deja calcule par des regles deterministes. "
    "Tu ne proposes JAMAIS de prix d'entree, de stop loss ou de take profit : "
    "ils sont fixes et non negociables. Ton role est d'expliquer le contexte "
    "et de signaler les risques. Reponds en francais, en JSON, avec les "
    "champs direction, confidence et summary."
)


class ConsensusLike(Protocol):
    """Sous-ensemble de ``ConsensusResult`` reellement utilise ici."""

    outcome: Any
    direction: Any
    confidence: float
    detail: str

    @property
    def blocks_auto_trade(self) -> bool: ...


class AIServiceLike(Protocol):
    """Sous-ensemble de ``ai_service`` necessaire au commentaire."""

    async def consensus(self, prompt: str, **kwargs: Any) -> ConsensusLike: ...

    def requires_manual_review(self, result: ConsensusLike) -> bool: ...


def build_prompt(draft: OpportunityDraft) -> str:
    """Prompt de commentaire : les niveaux y sont donnes, jamais demandes."""
    targets = ", ".join(f"{value:g}" for value in draft.levels.take_profits) or "aucune"
    lines = [
        f"Instrument : {draft.symbol}",
        f"Direction envisagee : {draft.direction.value}",
        f"Strategie : {draft.strategy}",
        f"Regime de marche : {draft.regime.value if draft.regime else 'inconnu'}",
        "",
        "Plan deja calcule (NE PAS MODIFIER, NE PAS EN PROPOSER D'AUTRE) :",
        f"  entree {draft.levels.entry_price:g} "
        f"(zone {draft.levels.entry_min:g} - {draft.levels.entry_max:g})",
        f"  stop loss {draft.levels.stop_loss:g}",
        f"  cibles {targets}",
        f"  rapport gain/risque attendu {draft.levels.expected_rr}",
        "",
        f"Score de confiance deterministe : {draft.confidence.score:.0f}/100",
        "Composantes :",
    ]
    for factor in draft.confidence.factors:
        if factor.score is None:
            lines.append(f"  - {factor.component.value} : indisponible")
        else:
            lines.append(
                f"  - {factor.component.value} : {factor.score:.0f}/100 "
                f"(poids {factor.weight:.2f})"
            )
    lines.append("")
    lines.append(
        "Explique en quelques phrases ce que montre ce contexte et ce qui pourrait "
        "invalider le scenario. N'indique aucun prix."
    )
    return "\n".join(lines)


async def annotate(
    draft: OpportunityDraft,
    service: AIServiceLike,
    *,
    decision_id: int | None = None,
) -> OpportunityDraft:
    """Ajoute le commentaire des modeles au brouillon, sans toucher aux prix.

    Seuls ``ai_comment`` et, via le retour, la vue de consensus sont derives de
    la reponse des modeles. Les niveaux du brouillon ne sont jamais relus ni
    reecrits.
    """
    try:
        result = await service.consensus(
            build_prompt(draft),
            system=SYSTEM_PROMPT,
            task=AITaskKind.OPPORTUNITY_REVIEW,
            deterministic_direction=draft.direction,
            deterministic_score=draft.confidence.ratio,
            decision_id=decision_id,
        )
    except Exception as exc:  # une explication ratee ne casse pas l'opportunite
        logger.info("Commentaire IA indisponible pour %s : %s", draft.symbol, exc)
        return draft

    detail = getattr(result, "detail", "") or ""
    draft.ai_comment = detail.strip()[:1000] or None
    return draft


def consensus_view(result: ConsensusLike, needs_review: bool) -> ConsensusView:
    """Traduit un ``ConsensusResult`` en composante de confiance.

    La direction et la confiance sont reprises telles quelles ; aucun prix
    n'est lu dans la reponse des modeles.
    """
    blocks = bool(getattr(result, "blocks_auto_trade", False))
    return ConsensusView(
        score=None if blocks else max(0.0, min(1.0, float(getattr(result, "confidence", 0.0)))),
        direction=getattr(result, "direction", None),
        available=not blocks,
        blocks_auto_trade=blocks,
        needs_manual_review=needs_review,
        detail=(getattr(result, "detail", "") or "")[:500] or None,
    )


__all__ = ["SYSTEM_PROMPT", "annotate", "build_prompt", "consensus_view"]
