"""Intelligence de marche autonome : assemblage, cycle et ordonnancement.

Les moteurs du CDC2 (donnees de marche, technique, regime, scanner, analogues,
actualites, calendrier, opportunites, decision, confiance, notifications) sont
livres separement. Ce paquet les relie et les fait tourner.
"""

from app.services.intelligence.assembly import build_bundle, news_view, price_structure
from app.services.intelligence.cycle import (
    CycleReport,
    SymbolOutcome,
    notify_major_news,
    notify_upcoming_events,
    run_cycle,
)
from app.services.intelligence.scheduler import (
    IntelligenceScheduler,
    LoopState,
    SchedulerState,
    intelligence_scheduler,
)

__all__ = [
    "CycleReport",
    "IntelligenceScheduler",
    "LoopState",
    "SchedulerState",
    "SymbolOutcome",
    "build_bundle",
    "intelligence_scheduler",
    "news_view",
    "notify_major_news",
    "notify_upcoming_events",
    "price_structure",
    "run_cycle",
]
