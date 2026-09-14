"""AI Market Watcher : surveillance de marche et publication de signaux (CDC3).

Sous-systeme autonome du Bridge TradePilot. Il demarre avec lui, analyse les
marches en continu, produit des signaux expliques et les publie dans un canal
Telegram.

Etanche par construction :

* toutes ses tables sont prefixees ``watcher_`` ;
* il lit les services existants (MetaTrader, analyse technique, actualites,
  IA, session Telegram) sans jamais les modifier ;
* il n'importe aucun module d'execution d'ordres. Le watcher ne peut pas
  passer d'ordre, meme par erreur (CDC3 section 44).

Importer ce paquet enregistre ses tables aupres de SQLModel : c'est
volontaire, et c'est ce qui permet a ``init_database`` de les creer sans que
``app.models`` ait a connaitre le watcher.
"""

from app.watcher import models  # noqa: F401  (enregistre les tables watcher_*)
from app.watcher.config import WatcherConfig, load_config, update_config
from app.watcher.engine import AnalysisOutcome, WatcherEngine
from app.watcher.lifecycle import LifecycleReport, LifecycleTracker
from app.watcher.models import (
    STRATEGY_VERSION,
    EntryType,
    RiskVerdict,
    VolatilityLevel,
    WatcherAnalysis,
    WatcherDecision,
    WatcherSignal,
    WatcherSignalEvent,
    WatcherStatus,
)
from app.watcher.publisher import TelegramPublisher, telegram_publisher
from app.watcher.scheduler import WatcherScheduler, watcher_scheduler

__all__ = [
    "STRATEGY_VERSION",
    "AnalysisOutcome",
    "EntryType",
    "LifecycleReport",
    "LifecycleTracker",
    "RiskVerdict",
    "TelegramPublisher",
    "VolatilityLevel",
    "WatcherAnalysis",
    "WatcherConfig",
    "WatcherDecision",
    "WatcherEngine",
    "WatcherScheduler",
    "WatcherSignal",
    "WatcherSignalEvent",
    "WatcherStatus",
    "load_config",
    "telegram_publisher",
    "update_config",
    "watcher_scheduler",
]
