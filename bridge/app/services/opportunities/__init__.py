"""Generation d'opportunites (CDC2 sections 40 et 41)."""

from app.services.opportunities.generator import (
    GeneratorConfig,
    OpportunityDraft,
    OpportunityGenerator,
    opportunity_generator,
)
from app.services.opportunities.narrative import annotate, build_prompt, consensus_view
from app.services.opportunities.planner import (
    LevelPlanner,
    PlannerConfig,
    PlanRejection,
    PlanResult,
    level_planner,
)

__all__ = [
    "GeneratorConfig",
    "LevelPlanner",
    "OpportunityDraft",
    "OpportunityGenerator",
    "PlanRejection",
    "PlanResult",
    "PlannerConfig",
    "annotate",
    "build_prompt",
    "consensus_view",
    "level_planner",
    "opportunity_generator",
]
