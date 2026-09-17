"""Reglages du Market Watcher (CDC3 sections 51, 52 et 53).

Trois sources, dans cet ordre de priorite croissante :

1. les valeurs par defaut ecrites ici, qui suffisent a faire tourner le
   systeme sans aucune configuration ;
2. ``config/watcher.yaml`` a la racine du projet, qui permet de changer les
   seuils sans toucher au code ni passer par l'API ;
3. les reglages ``watcher.*`` en base, modifiables a chaud depuis l'API.

Aucun secret ne transite ici : les identifiants Telegram, MetaTrader et
OpenRouter restent ceux du Bridge (CDC3 section 58).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.config.settings import BRIDGE_ROOT
from app.repositories import settings_repo

logger = get_logger(__name__)

SETTING_PREFIX = "watcher."
YAML_PATH = BRIDGE_ROOT.parent / "config" / "watcher.yaml"

# Instruments proposes par le CDC3 section 1. Ce n'est qu'une proposition :
# ceux qui n'existent pas chez le broker sont ecartes au demarrage, jamais
# supposes disponibles.
#
# Les noms sont ceux que le SymbolResolver du Bridge sait traduire vers le
# catalogue du courtier : il resout NAS100 vers USTECm et US500 vers US500m
# chez Exness. « SPX500 » n'est en revanche pas un nom canonique connu de ce
# resolveur — c'est US500 qu'il faut demander.
DEFAULT_SYMBOLS: tuple[str, ...] = (
    "BTCUSD",
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "ETHUSD",
    "US30",
    "NAS100",
    "US500",
)

# Ponderations du score global (CDC3 section 24). La somme fait 100.
DEFAULT_WEIGHTS: dict[str, float] = {
    "market_structure": 20.0,
    "multi_timeframe": 15.0,
    "momentum": 10.0,
    "support_resistance": 10.0,
    "volume": 5.0,
    "volatility": 5.0,
    "indicators": 10.0,
    "sentiment": 10.0,
    "fundamental": 10.0,
    "risk_reward": 5.0,
}

# Duree pendant laquelle la configuration lue en base est reutilisee. Assez
# courte pour qu'un changement depuis l'API soit pris en compte sans
# redemarrage, assez longue pour ne pas interroger la base a chaque bougie.
CACHE_TTL_SECONDS = 30.0


@dataclass(slots=True)
class WatcherConfig:
    """Configuration complete du Market Watcher."""

    # --- cycle de vie du service ---
    enabled: bool = True
    # DRY_RUN analyse et enregistre tout, mais ne publie rien (CDC3 section 62).
    dry_run: bool = False
    symbols: list[str] = field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    profile: str = "default"
    scan_interval_seconds: float = 90.0
    lifecycle_interval_seconds: float = 30.0
    performance_interval_minutes: float = 15.0
    bars: int = 300

    # --- seuils de decision (CDC3 sections 24 et 53) ---
    minimum_score: float = 70.0
    watch_score: float = 55.0
    strong_score: float = 85.0
    minimum_rr: float = 1.5

    # --- filtres du Risk Manager (CDC3 section 30) ---
    max_spread_points: int = 60
    # Un spread superieur a cette fraction de l'ATR rend le setup ininteressant
    # quel que soit son nombre de points : un point ne veut rien dire sans
    # l'amplitude de l'instrument.
    max_spread_atr_ratio: float = 0.25
    block_high_impact_news: bool = True
    before_news_minutes: int = 15
    after_news_minutes: int = 15
    critical_news_minutes: int = 30
    block_extreme_volatility: bool = True
    # L'unite de confirmation du profil doit donner son feu vert avant toute
    # entree. Mesure du 17/09/2026 sur les 41 premiers signaux denoues :
    # ENTRY_CONFIRMATION 19 signaux a +10,14 R et 68 % de gagnants, WAIT 22
    # signaux a -11,69 R et 23 % de gagnants. C'est le critere le plus
    # discriminant du systeme, et il n'etait qu'un contributeur a une moyenne
    # ponderee -- qu'un market_structure fort pouvait outvoter.
    require_entry_confirmation: bool = True

    # --- qualite des donnees (CDC3 section 66) ---
    # Plancher de tolerance sur l'age de la derniere bougie. La tolerance
    # reelle vaut deux bougies de l'unite de temps analysee : une bougie M15
    # qui vient de s'ouvrir a legitimement quinze minutes, et un plafond fixe
    # plus court bloquerait tous les signaux en permanence.
    max_data_age_seconds: int = 600
    minimum_candles: int = 120

    # --- anti-spam (CDC3 section 31) ---
    cooldown_minutes: int = 45
    signal_ttl_minutes: int = 240
    max_active_signals: int = 6
    max_signals_per_day: int = 12
    watch_alert_cooldown_minutes: int = 120

    # --- Telegram (CDC3 sections 33 a 37) ---
    telegram_channel: str = "tradepilot test"
    telegram_channel_id: int | None = None
    telegram_format: str = "detailed"
    send_watch_alerts: bool = True
    send_news_alerts: bool = True
    send_signal_updates: bool = True
    send_startup_message: bool = True

    # --- passage a l'acte (CDC3 section 25) ---
    # Le watcher ne se contente plus de publier : sa decision est remise au
    # moteur de trading, qui la fait passer par le parser, la verification IA,
    # le RiskManager puis MetaTrader. Mettre ce reglage a False rend au
    # watcher son role de simple publicateur.
    auto_trade: bool = True

    # --- IA (CDC3 sections 20 et 73) ---
    ai_enabled: bool = True
    # En dessous de ce score, aucun appel LLM : l'analyse deterministe a deja
    # tranche, payer un jeton n'apporterait rien (CDC3 section 73).
    ai_min_score: float = 60.0

    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    # --- mesure en avant de la bande sous le seuil ---
    # Un fantome est un signal que le systeme aurait publie si le seuil avait
    # ete plus bas. Il est suivi comme un vrai mais jamais publie, jamais
    # execute, et invisible pour les decisions reelles. C'est le capteur qui
    # rend une baisse de seuil justifiable au lieu d'etre un pari : sans lui,
    # personne ne sait ce que vaut la bande qu'on s'apprete a ouvrir.
    shadow_enabled: bool = True
    shadow_score: float = 65.0

    # --- apprentissage sur les pertes (CDC3 section 41) ---
    # Il n'ecarte qu'une clef sans un seul gain, et n'ajuste jamais un
    # parametre dont la borne n'est pas ecrite ici : sans limite declaree,
    # rien ne dit jusqu'ou il aurait le droit d'aller.
    learning_enabled: bool = True
    learning_window_days: int = 30
    learning_bounds: dict[str, list[float]] = field(
        default_factory=lambda: {"minimum_score": [65.0, 80.0], "minimum_rr": [1.2, 2.5]}
    )
    # Types d'entree ecartes par l'apprentissage. Se defait depuis l'app :
    # une decision n'est qu'un reglage, jamais du code.
    disabled_entry_types: list[str] = field(default_factory=list)
    # Bande dans laquelle un poids de critere peut etre deplace. Le plancher
    # n'est pas zero : eteindre un critere serait un changement de structure,
    # pas un reglage, et un critere muet ne peut plus jamais se racheter
    # puisqu'il ne pese plus sur aucun resultat a mesurer. Le plafond empeche
    # un seul critere de decider a la place des dix.
    weight_floor: float = 2.0
    weight_ceiling: float = 30.0
    # Taille de l'echantillon au dernier ajustement. Un pas n'est autorise que
    # si la mesure a grossi depuis : sans cela, dix operations rentables
    # feraient descendre le seuil d'un point TOUTES LES HEURES jusqu'a la
    # borne, soit cinq pas payes d'une seule et meme mesure.
    #
    # Un compteur par SENS, car les deux se mesurent sur des populations
    # distinctes : la baisse sur la bande fantome, la hausse sur le publie. Un
    # compteur commun ferait passer l'une pour la repetition de l'autre et
    # bloquerait une preuve pourtant neuve.
    threshold_down_sample: int = 0
    threshold_up_sample: int = 0
    weights_last_sample: int = 0

    @property
    def simple_format(self) -> bool:
        return self.telegram_format.strip().lower() == "simple"

    def weight(self, key: str) -> float:
        """Ponderation d'un critere, repli sur la valeur d'origine."""
        return float(self.weights.get(key, DEFAULT_WEIGHTS.get(key, 0.0)))

    @property
    def total_weight(self) -> float:
        """Somme des ponderations reellement appliquees.

        Elle passe par ``weight()`` critere par critere, et non par la somme
        des valeurs fournies : une ponderation partielle — trois criteres
        redefinis dans le YAML, les sept autres laisses par defaut — donnerait
        sinon un total qui ne correspond a aucun calcul, et la couverture
        deviendrait fausse.
        """
        keys = set(DEFAULT_WEIGHTS) | set(self.weights)
        total = sum(self.weight(key) for key in keys)
        return total if total > 0 else 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "dryRun": self.dry_run,
            "symbols": list(self.symbols),
            "profile": self.profile,
            "scanIntervalSeconds": self.scan_interval_seconds,
            "lifecycleIntervalSeconds": self.lifecycle_interval_seconds,
            "performanceIntervalMinutes": self.performance_interval_minutes,
            "bars": self.bars,
            "minimumScore": self.minimum_score,
            "watchScore": self.watch_score,
            "strongScore": self.strong_score,
            "minimumRr": self.minimum_rr,
            # La bande mesuree sous le seuil, et de quoi la lire : sans ces
            # deux valeurs, l'application ne peut pas dire ou commence ni ou
            # s'arrete ce qu'elle compare.
            "shadowEnabled": self.shadow_enabled,
            "shadowScore": self.shadow_score,
            "maxSpreadPoints": self.max_spread_points,
            "maxSpreadAtrRatio": self.max_spread_atr_ratio,
            "blockHighImpactNews": self.block_high_impact_news,
            "beforeNewsMinutes": self.before_news_minutes,
            "afterNewsMinutes": self.after_news_minutes,
            "criticalNewsMinutes": self.critical_news_minutes,
            "blockExtremeVolatility": self.block_extreme_volatility,
            "requireEntryConfirmation": self.require_entry_confirmation,
            "maxDataAgeSeconds": self.max_data_age_seconds,
            "minimumCandles": self.minimum_candles,
            "cooldownMinutes": self.cooldown_minutes,
            "signalTtlMinutes": self.signal_ttl_minutes,
            "maxActiveSignals": self.max_active_signals,
            "maxSignalsPerDay": self.max_signals_per_day,
            "watchAlertCooldownMinutes": self.watch_alert_cooldown_minutes,
            "telegramChannel": self.telegram_channel,
            "telegramChannelId": self.telegram_channel_id,
            "telegramFormat": self.telegram_format,
            "sendWatchAlerts": self.send_watch_alerts,
            "sendNewsAlerts": self.send_news_alerts,
            "sendSignalUpdates": self.send_signal_updates,
            "sendStartupMessage": self.send_startup_message,
            "aiEnabled": self.ai_enabled,
            "aiMinScore": self.ai_min_score,
            "weights": dict(self.weights),
        }


# Nom du champ Python -> type attendu, deduit une fois pour toutes.
_FIELD_TYPES: dict[str, Any] = {item.name: item.type for item in fields(WatcherConfig)}


def _coerce(name: str, raw: Any, current: Any) -> Any:
    """Convertit une valeur brute vers le type du champ, sans jamais lever.

    Une valeur illisible est ignoree avec un avertissement : un reglage mal
    saisi ne doit pas empecher le systeme de tourner (CDC3 section 55).
    """
    declared = str(_FIELD_TYPES.get(name, ""))
    try:
        # Traite avant les branches generiques : son type declare
        # ``dict[str, list[float]]`` contient « list », donc la conversion des
        # listes le capturerait et les bornes du YAML seraient perdues en
        # silence. Ses valeurs sont des paires, pas des nombres.
        if name == "learning_bounds":
            if not isinstance(raw, dict):
                return current
            bornes: dict[str, list[float]] = {}
            for key, value in raw.items():
                if isinstance(value, (list, tuple)) and len(value) == 2:
                    bornes[str(key)] = [float(value[0]), float(value[1])]
                else:
                    logger.warning(
                        "Borne watcher.learning_bounds.%s ignoree : une paire est attendue.",
                        key,
                    )
            return bornes
        if "bool" in declared:
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in {"1", "true", "vrai", "oui", "yes", "on"}
        if "list" in declared:
            if isinstance(raw, (list, tuple)):
                return [str(item).strip().upper() for item in raw if str(item).strip()]
            return [part.strip().upper() for part in str(raw).split(",") if part.strip()]
        if "dict" in declared:
            if isinstance(raw, dict):
                # Une ponderation partielle complete les valeurs d'origine
                # plutot que de les effacer : redefinir trois criteres ne doit
                # pas faire disparaitre les sept autres.
                merged = dict(DEFAULT_WEIGHTS) if name == "weights" else {}
                merged.update({str(key): float(value) for key, value in raw.items()})
                return merged
            return current
        if name == "telegram_channel_id":
            return int(raw) if str(raw).strip() else None
        if "int" in declared:
            return int(float(raw))
        if "float" in declared:
            return float(raw)
        return str(raw)
    except (TypeError, ValueError):
        logger.warning("Reglage watcher.%s ignore : valeur illisible.", name)
        return current


def _yaml_overrides() -> dict[str, Any]:
    """Valeurs lues dans ``config/watcher.yaml``, vide si le fichier est absent.

    PyYAML arrive avec uvicorn ; s'il manquait, l'absence du fichier de
    configuration ne doit pas empecher le demarrage.
    """
    path: Path = YAML_PATH
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        logger.info("PyYAML absent : %s est ignore, les valeurs par defaut s'appliquent.", path.name)
        return {}
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Fichier %s illisible : %s", path.name, exc)
        return {}
    if not isinstance(content, dict):
        return {}
    return {str(key): value for key, value in content.items()}


_cache: tuple[float, WatcherConfig] | None = None


async def load_config(session: AsyncSession, refresh: bool = False) -> WatcherConfig:
    """Configuration courante : defauts, puis YAML, puis reglages en base."""
    global _cache
    now = time.monotonic()
    if not refresh and _cache is not None and now - _cache[0] <= CACHE_TTL_SECONDS:
        return _cache[1]

    config = WatcherConfig()
    for name, raw in _yaml_overrides().items():
        if name in _FIELD_TYPES:
            setattr(config, name, _coerce(name, raw, getattr(config, name)))

    for name in _FIELD_TYPES:
        stored = await settings_repo.get_setting(session, f"{SETTING_PREFIX}{name}", None)
        if stored is None:
            continue
        setattr(config, name, _coerce(name, stored, getattr(config, name)))

    _cache = (now, config)
    return config


async def update_config(session: AsyncSession, changes: dict[str, Any]) -> WatcherConfig:
    """Ecrit les reglages fournis puis rend la configuration relue.

    Les cles inconnues sont refusees explicitement plutot qu'ignorees en
    silence : un reglage mal orthographie doit se voir.
    """
    unknown = [key for key in changes if key not in _FIELD_TYPES]
    if unknown:
        raise ValueError(f"Reglages inconnus : {', '.join(sorted(unknown))}")
    reference = WatcherConfig()
    for key, value in changes.items():
        coerced = _coerce(key, value, getattr(reference, key))
        await settings_repo.set_setting(session, f"{SETTING_PREFIX}{key}", coerced)
    return await load_config(session, refresh=True)


def invalidate_cache() -> None:
    """Oublie la configuration memorisee (tests, changement de base)."""
    global _cache
    _cache = None


__all__ = [
    "DEFAULT_SYMBOLS",
    "DEFAULT_WEIGHTS",
    "SETTING_PREFIX",
    "WatcherConfig",
    "invalidate_cache",
    "load_config",
    "update_config",
]
