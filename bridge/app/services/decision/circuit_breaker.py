"""Coupe-circuit du trading automatique (CDC2 section 86).

Il ne remplace pas le RiskManager : il se place avant lui et suspend purement
et simplement l'automatisme quand l'environnement n'est plus fiable. Chaque
declenchement porte un motif lisible, consultable depuis l'application.

Le coupe-circuit ne se referme jamais tout seul sur un motif structurel
(drawdown, pertes en serie) : seule une remise a zero explicite ou la
disparition mesuree de la cause le reouvre.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from app.config.logging_config import get_logger
from app.models.core import utcnow

logger = get_logger(__name__)


class BreakerReason(StrEnum):
    """Motifs listes par le CDC2 section 86."""

    INCONSISTENT_DATA = "INCONSISTENT_DATA"
    MT5_UNSTABLE = "MT5_UNSTABLE"
    ABNORMAL_SPREAD = "ABNORMAL_SPREAD"
    TOO_MANY_ERRORS = "TOO_MANY_ERRORS"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    BRIDGE_UNSTABLE = "BRIDGE_UNSTABLE"
    AI_CONSENSUS_UNAVAILABLE = "AI_CONSENSUS_UNAVAILABLE"


# Motifs qui disparaissent d'eux-memes des que la mesure redevient normale.
TRANSIENT_REASONS = frozenset(
    {
        BreakerReason.INCONSISTENT_DATA,
        BreakerReason.MT5_UNSTABLE,
        BreakerReason.ABNORMAL_SPREAD,
        BreakerReason.BRIDGE_UNSTABLE,
        BreakerReason.AI_CONSENSUS_UNAVAILABLE,
    }
)

REASON_LABELS: dict[BreakerReason, str] = {
    BreakerReason.INCONSISTENT_DATA: "Données de marché incohérentes",
    BreakerReason.MT5_UNSTABLE: "Terminal MetaTrader 5 instable",
    BreakerReason.ABNORMAL_SPREAD: "Spread anormal",
    BreakerReason.TOO_MANY_ERRORS: "Trop d'erreurs sur une courte période",
    BreakerReason.MAX_DRAWDOWN: "Drawdown maximal atteint",
    BreakerReason.CONSECUTIVE_LOSSES: "Pertes consécutives",
    BreakerReason.BRIDGE_UNSTABLE: "Bridge instable",
    BreakerReason.AI_CONSENSUS_UNAVAILABLE: "Consensus IA obligatoire indisponible",
}


@dataclass(slots=True)
class BreakerLimits:
    """Seuils de declenchement, tous configurables."""

    max_errors: int = 5
    error_window_seconds: int = 300
    max_drawdown_percent: float = 10.0
    max_consecutive_losses: int = 4
    max_spread_ratio: float = 3.0

    def __post_init__(self) -> None:
        if self.max_errors < 1:
            raise ValueError("max_errors doit valoir au moins 1.")
        if self.error_window_seconds < 1:
            raise ValueError("error_window_seconds doit être strictement positif.")


@dataclass(slots=True)
class TrippedReason:
    reason: BreakerReason
    message: str
    since: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "label": REASON_LABELS[self.reason],
            "message": self.message,
            "since": self.since.isoformat(),
        }


@dataclass(slots=True)
class BreakerState:
    """Etat consultable du coupe-circuit."""

    tripped: bool = False
    reasons: list[TrippedReason] = field(default_factory=list)
    since: datetime | None = None

    @property
    def allows_auto_trading(self) -> bool:
        return not self.tripped

    @property
    def summary(self) -> str | None:
        """Motif affichable, en francais accentue."""
        if not self.reasons:
            return None
        return " ; ".join(item.message for item in self.reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tripped": self.tripped,
            "allowsAutoTrading": self.allows_auto_trading,
            "since": self.since.isoformat() if self.since else None,
            "summary": self.summary,
            "reasons": [item.to_dict() for item in self.reasons],
        }


class CircuitBreaker:
    """Surveille l'environnement et suspend l'automatisme si besoin."""

    def __init__(self, limits: BreakerLimits | None = None) -> None:
        self._limits = limits or BreakerLimits()
        self._active: dict[BreakerReason, TrippedReason] = {}
        self._errors: deque[datetime] = deque()
        self._consecutive_losses = 0
        self._drawdown_percent: float | None = None

    @property
    def limits(self) -> BreakerLimits:
        return self._limits

    # ------------------------------------------------------------------
    # Declenchement et levee
    # ------------------------------------------------------------------
    def trip(
        self, reason: BreakerReason, message: str, *, now: datetime | None = None
    ) -> BreakerState:
        moment = now or utcnow()
        if reason not in self._active:
            self._active[reason] = TrippedReason(reason=reason, message=message, since=moment)
            logger.warning("Coupe-circuit declenche (%s) : %s", reason.value, message)
        else:
            self._active[reason].message = message
        return self.state

    def clear(self, reason: BreakerReason) -> BreakerState:
        """Leve un motif transitoire. Les motifs structurels resistent."""
        if reason in TRANSIENT_REASONS:
            self._active.pop(reason, None)
        return self.state

    def reset(self, *, actor: str = "system") -> BreakerState:
        """Remise a zero explicite : c'est une action volontaire, tracee."""
        self._active.clear()
        self._errors.clear()
        self._consecutive_losses = 0
        self._drawdown_percent = None
        logger.info("Coupe-circuit reinitialise par %s", actor)
        return self.state

    # ------------------------------------------------------------------
    # Mesures entrantes
    # ------------------------------------------------------------------
    def record_error(self, detail: str = "", *, now: datetime | None = None) -> BreakerState:
        """Compte une erreur technique dans la fenetre glissante."""
        moment = now or utcnow()
        self._errors.append(moment)
        self._prune_errors(moment)
        if len(self._errors) >= self._limits.max_errors:
            message = (
                f"{len(self._errors)} erreurs en moins de "
                f"{self._limits.error_window_seconds} secondes."
            )
            if detail:
                message = f"{message} Dernière : {detail}"
            return self.trip(BreakerReason.TOO_MANY_ERRORS, message, now=moment)
        return self.state

    def record_trade_result(self, won: bool, *, now: datetime | None = None) -> BreakerState:
        """Suit la serie de pertes. Un gain remet le compteur a zero."""
        if won:
            self._consecutive_losses = 0
            self._active.pop(BreakerReason.CONSECUTIVE_LOSSES, None)
            return self.state
        self._consecutive_losses += 1
        if self._consecutive_losses >= self._limits.max_consecutive_losses:
            return self.trip(
                BreakerReason.CONSECUTIVE_LOSSES,
                f"{self._consecutive_losses} pertes consécutives.",
                now=now,
            )
        return self.state

    def report_drawdown(
        self, percent: float | None, *, now: datetime | None = None
    ) -> BreakerState:
        """Drawdown courant en pourcentage. ``None`` : mesure indisponible."""
        self._drawdown_percent = percent
        if percent is None:
            return self.state
        if percent >= self._limits.max_drawdown_percent:
            return self.trip(
                BreakerReason.MAX_DRAWDOWN,
                f"Drawdown de {percent:.2f} % (limite {self._limits.max_drawdown_percent:.2f} %).",
                now=now,
            )
        return self.state

    def report_market_data(
        self, consistent: bool, detail: str = "", *, now: datetime | None = None
    ) -> BreakerState:
        if consistent:
            return self.clear(BreakerReason.INCONSISTENT_DATA)
        return self.trip(
            BreakerReason.INCONSISTENT_DATA,
            detail or "Les données de marché reçues sont incohérentes.",
            now=now,
        )

    def report_spread(
        self,
        symbol: str,
        spread_points: float | None,
        normal_points: float | None,
        *,
        now: datetime | None = None,
    ) -> BreakerState:
        """Compare le spread au spread habituel. Sans reference : rien a dire."""
        if spread_points is None or normal_points is None or normal_points <= 0:
            return self.state
        ratio = spread_points / normal_points
        if ratio >= self._limits.max_spread_ratio:
            return self.trip(
                BreakerReason.ABNORMAL_SPREAD,
                f"Spread {symbol} à {spread_points:.0f} points, soit {ratio:.1f} fois la normale.",
                now=now,
            )
        return self.clear(BreakerReason.ABNORMAL_SPREAD)

    def report_mt5(
        self, connected: bool, stable: bool = True, *, now: datetime | None = None
    ) -> BreakerState:
        if connected and stable:
            return self.clear(BreakerReason.MT5_UNSTABLE)
        message = (
            "MetaTrader 5 est déconnecté."
            if not connected
            else "MetaTrader 5 répond de façon instable."
        )
        return self.trip(BreakerReason.MT5_UNSTABLE, message, now=now)

    def report_bridge(
        self, healthy: bool, detail: str = "", *, now: datetime | None = None
    ) -> BreakerState:
        if healthy:
            return self.clear(BreakerReason.BRIDGE_UNSTABLE)
        return self.trip(
            BreakerReason.BRIDGE_UNSTABLE,
            detail or "Le Bridge est instable.",
            now=now,
        )

    def report_ai_consensus(
        self, available: bool, required: bool = True, *, now: datetime | None = None
    ) -> BreakerState:
        """Le consensus obligatoire manquant suspend l'automatisme."""
        if available or not required:
            return self.clear(BreakerReason.AI_CONSENSUS_UNAVAILABLE)
        return self.trip(
            BreakerReason.AI_CONSENSUS_UNAVAILABLE,
            "Le consensus IA est obligatoire mais aucune intelligence n'a répondu.",
            now=now,
        )

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    @property
    def state(self) -> BreakerState:
        reasons = sorted(self._active.values(), key=lambda item: item.since)
        return BreakerState(
            tripped=bool(reasons),
            reasons=list(reasons),
            since=reasons[0].since if reasons else None,
        )

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    def recent_errors(self, *, now: datetime | None = None) -> int:
        self._prune_errors(now or utcnow())
        return len(self._errors)

    def to_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        payload = self.state.to_dict()
        payload["metrics"] = {
            "recentErrors": self.recent_errors(now=now),
            "consecutiveLosses": self._consecutive_losses,
            "drawdownPercent": self._drawdown_percent,
        }
        payload["limits"] = {
            "maxErrors": self._limits.max_errors,
            "errorWindowSeconds": self._limits.error_window_seconds,
            "maxDrawdownPercent": self._limits.max_drawdown_percent,
            "maxConsecutiveLosses": self._limits.max_consecutive_losses,
            "maxSpreadRatio": self._limits.max_spread_ratio,
        }
        return payload

    # ------------------------------------------------------------------
    def _prune_errors(self, now: datetime) -> None:
        horizon = now - timedelta(seconds=self._limits.error_window_seconds)
        while self._errors and self._errors[0] < horizon:
            self._errors.popleft()


circuit_breaker = CircuitBreaker()

__all__ = [
    "REASON_LABELS",
    "TRANSIENT_REASONS",
    "BreakerLimits",
    "BreakerReason",
    "BreakerState",
    "CircuitBreaker",
    "TrippedReason",
    "circuit_breaker",
]
