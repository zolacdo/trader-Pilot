"""Moteur d'apprentissage (CDC2 section 49).

Le systeme mesure ses propres resultats et les presente. Il ne reecrit jamais
ses regles : ``AUTOMATIC_RULE_UPDATES`` vaut False et aucune fonction de ce
paquet ne modifie un parametre de trading.
"""

from __future__ import annotations

from app.services.learning.performance import (
    by_day,
    by_regime,
    by_source,
    by_strategy,
    overview,
)
from app.services.learning.recorder import (
    AUTOMATIC_RULE_UPDATES,
    LEARNING_CATEGORY,
    LEARNING_EVENT,
    LEARNING_NOTE,
    UNSPECIFIED_STRATEGY,
    TradeLearningRecord,
    aggregate,
    collect_records,
    record_trade_outcome,
)

__all__ = [
    "AUTOMATIC_RULE_UPDATES",
    "LEARNING_CATEGORY",
    "LEARNING_EVENT",
    "LEARNING_NOTE",
    "UNSPECIFIED_STRATEGY",
    "TradeLearningRecord",
    "aggregate",
    "by_day",
    "by_regime",
    "by_source",
    "by_strategy",
    "collect_records",
    "overview",
    "record_trade_outcome",
]
