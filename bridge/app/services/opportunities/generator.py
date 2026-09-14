"""Generation d'opportunites par le systeme lui-meme (CDC2 section 40).

TradePilot n'attend pas qu'on lui envoie un signal : quand une structure et un
regime s'y pretent, il formule sa propre proposition. Elle reste une
proposition — le moteur de decision et le RiskManager gardent le dernier mot.

Les niveaux viennent exclusivement du planificateur deterministe
(CDC2 section 41). Aucune valeur n'est demandee a un modele, ni acceptee de sa
part. Sans plan calculable, aucune opportunite n'est produite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.config.logging_config import get_logger
from app.models.core import utcnow
from app.models.enums import Direction
from app.models.intelligence import AiOpportunity, MarketRegime
from app.services.confidence.engine import ConfidenceEngine, ConfidenceResult
from app.services.decision.inputs import AnalysisBundle, PriceStructure, TradeLevels
from app.services.opportunities.planner import LevelPlanner, PlanRejection
from app.services.strategies.base import StrategyProposal
from app.services.strategies.registry import StrategyRegistry, strategy_registry

logger = get_logger(__name__)


@dataclass(slots=True)
class GeneratorConfig:
    """Reglages de production des opportunites."""

    # Confiance minimale pour qu'une opportunite soit jugee exploitable.
    min_confidence: float = 0.75
    # Duree de validite : une opportunite perimee ne doit plus etre proposee.
    validity_minutes: int = 120
    # RR minimal attendu sur la premiere cible.
    min_first_target_rr: float = 1.0


@dataclass(slots=True)
class OpportunityDraft:
    """Opportunite complete, prete a etre enregistree ou refusee."""

    symbol: str
    direction: Direction
    proposal: StrategyProposal
    levels: TradeLevels
    confidence: ConfidenceResult
    reasons: list[str] = field(default_factory=list)
    negative_factors: list[str] = field(default_factory=list)
    regime: MarketRegime | None = None
    created_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    qualified: bool = False
    # Commentaire produit par les modeles : il explique, il ne chiffre rien.
    ai_comment: str | None = None

    @property
    def strategy(self) -> str:
        return self.proposal.strategy

    def to_model(self, *, broker_symbol: str | None = None) -> AiOpportunity:
        return AiOpportunity(
            symbol=self.symbol,
            broker_symbol=broker_symbol,
            created_at=self.created_at,
            expires_at=self.expires_at,
            direction=self.direction,
            strategy=self.strategy,
            entry_min=self.levels.entry_min,
            entry_max=self.levels.entry_max,
            entry_price=self.levels.entry_price,
            stop_loss=self.levels.stop_loss,
            take_profits=list(self.levels.take_profits),
            expected_rr=self.levels.expected_rr,
            confidence=round(self.confidence.ratio, 4),
            status="PENDING" if self.qualified else "WATCHED",
            reasons=list(self.reasons),
            negative_factors=list(self.negative_factors),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "strategy": self.strategy,
            "regime": self.regime.value if self.regime else None,
            "qualified": self.qualified,
            "createdAt": self.created_at.isoformat(),
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "levels": self.levels.to_dict(),
            "confidence": self.confidence.to_dict(),
            "reasons": list(self.reasons),
            "negativeFactors": list(self.negative_factors),
            "aiComment": self.ai_comment,
        }


class OpportunityGenerator:
    """Assemble strategie, niveaux deterministes et confiance."""

    def __init__(
        self,
        registry: StrategyRegistry | None = None,
        planner: LevelPlanner | None = None,
        confidence: ConfidenceEngine | None = None,
        config: GeneratorConfig | None = None,
    ) -> None:
        self._registry = registry or strategy_registry
        self._planner = planner or LevelPlanner()
        self._confidence = confidence or ConfidenceEngine()
        self._config = config or GeneratorConfig()

    @property
    def config(self) -> GeneratorConfig:
        return self._config

    @property
    def registry(self) -> StrategyRegistry:
        return self._registry

    # ------------------------------------------------------------------
    def generate(
        self,
        bundle: AnalysisBundle,
        structure: PriceStructure,
        *,
        now: datetime | None = None,
    ) -> OpportunityDraft | None:
        """Produit une opportunite, ou rien du tout.

        Rendre ``None`` est un resultat normal et frequent : la plupart du
        temps, aucun setup ne se presente (CDC2 section 2).
        """
        proposal = self._registry.best(bundle, structure)
        if proposal is None:
            return None

        plan = self._planner.plan(proposal.direction, structure)
        if plan.levels is None:
            logger.info(
                "Opportunite %s abandonnee : %s",
                bundle.symbol,
                _rejection_text(plan.rejections),
            )
            return None

        levels = plan.levels
        if (levels.first_target_rr or 0.0) < self._config.min_first_target_rr:
            logger.info(
                "Opportunite %s abandonnee : RR de %.2f sur la première cible",
                bundle.symbol,
                levels.first_target_rr or 0.0,
            )
            return None

        components = bundle.components(proposal.direction)
        confidence = self._confidence.evaluate(components)

        moment = now or utcnow()
        draft = OpportunityDraft(
            symbol=bundle.symbol,
            direction=proposal.direction,
            proposal=proposal,
            levels=levels,
            confidence=confidence,
            regime=bundle.market_regime,
            created_at=moment,
            expires_at=moment + timedelta(minutes=self._config.validity_minutes),
            qualified=confidence.score >= self._config.min_confidence * 100.0,
        )
        draft.reasons = self._reasons(draft)
        draft.negative_factors = self._negatives(draft)
        return draft

    # ------------------------------------------------------------------
    @staticmethod
    def _reasons(draft: OpportunityDraft) -> list[str]:
        """Raisons positives, chiffrees, en francais accentue."""
        reasons = list(draft.proposal.reasons)
        if draft.regime is not None:
            reasons.append(f"Régime de marché : {draft.regime.value}.")
        reasons.extend(
            f"{item.label} : {item.score:.0f}/100." for item in draft.confidence.strongest()
        )
        if draft.levels.expected_rr is not None:
            reasons.append(
                f"Rapport gain/risque attendu de {draft.levels.expected_rr:.2f} "
                f"(première cible {draft.levels.first_target_rr:.2f})."
            )
        reasons.append(
            f"Niveaux calculés par règles déterministes ({draft.levels.method}), "
            "jamais proposés par un modèle."
        )
        return reasons

    @staticmethod
    def _negatives(draft: OpportunityDraft) -> list[str]:
        """Facteurs defavorables : ils doivent rester visibles."""
        negatives = list(draft.proposal.negative_factors)
        negatives.extend(
            f"{item.label} faible : {item.score:.0f}/100."
            for item in draft.confidence.weakest()
        )
        for component in draft.confidence.missing:
            negatives.append(f"Composante indisponible : {component.value}.")
        if not draft.qualified:
            negatives.append(
                f"Confiance de {draft.confidence.score:.0f}/100 sous le seuil d'exploitation."
            )
        return negatives


def _rejection_text(rejections: list[PlanRejection]) -> str:
    return " ".join(item.message for item in rejections) or "aucun plan calculable"


opportunity_generator = OpportunityGenerator()

__all__ = [
    "GeneratorConfig",
    "OpportunityDraft",
    "OpportunityGenerator",
    "opportunity_generator",
]
