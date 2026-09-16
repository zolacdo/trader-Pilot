"""Statistiques de performance des signaux (CDC3 sections 40, 41 et 82).

Tout est calcule sur des resultats reellement constates par le suivi du cycle
de vie. Aucune extrapolation, aucune simulation : un signal encore ouvert
n'entre dans aucune statistique de resultat.

Le module propose aussi une calibration par tranche de score (section 82) et
des recommandations de ponderation (section 41). Ces recommandations ne sont
JAMAIS appliquees automatiquement : elles sont affichees, et c'est un humain
qui tranche.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import as_utc, utcnow
from app.watcher import repository
from app.watcher.models import WatcherSignal, WatcherStatus

# Tranches de score utilisees pour la calibration (CDC3 section 82).
SCORE_BUCKETS: tuple[tuple[int, int], ...] = (
    (50, 60),
    (60, 70),
    (70, 80),
    (80, 90),
    (90, 101),
)

# En dessous de ce nombre de resultats, une statistique ne veut rien dire et
# n'est pas presentee comme une tendance.
MIN_SAMPLE = 10


@dataclass(slots=True)
class Bucket:
    """Agregat elementaire : gagnants, perdants, somme des R."""

    label: str
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    total_r: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    @property
    def trades(self) -> int:
        return self.wins + self.losses + self.breakeven

    @property
    def win_rate(self) -> float | None:
        return round(self.wins / self.trades * 100.0, 1) if self.trades else None

    @property
    def average_r(self) -> float | None:
        return round(self.total_r / self.trades, 3) if self.trades else None

    @property
    def profit_factor(self) -> float | None:
        """Rapport gains bruts / pertes brutes, en unites de risque."""
        if self.gross_loss <= 0:
            return None if self.gross_profit <= 0 else float("inf")
        return round(self.gross_profit / self.gross_loss, 2)

    @property
    def significant(self) -> bool:
        return self.trades >= MIN_SAMPLE

    def add(self, result: float) -> None:
        if result > 0:
            self.wins += 1
            self.gross_profit += result
        elif result < 0:
            self.losses += 1
            self.gross_loss += abs(result)
        else:
            self.breakeven += 1
        self.total_r += result

    def to_dict(self) -> dict[str, Any]:
        factor = self.profit_factor
        return {
            "label": self.label,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "breakeven": self.breakeven,
            "winRate": self.win_rate,
            "averageR": self.average_r,
            "totalR": round(self.total_r, 2),
            "profitFactor": None if factor == float("inf") else factor,
            "significant": self.significant,
        }


@dataclass(slots=True)
class PerformanceReport:
    """Bilan complet sur une fenetre glissante."""

    window_days: int
    generated_at: datetime = field(default_factory=utcnow)
    overall: Bucket = field(default_factory=lambda: Bucket("global"))
    by_symbol: dict[str, Bucket] = field(default_factory=dict)
    by_timeframe: dict[str, Bucket] = field(default_factory=dict)
    by_entry_type: dict[str, Bucket] = field(default_factory=dict)
    by_hour: dict[str, Bucket] = field(default_factory=dict)
    by_weekday: dict[str, Bucket] = field(default_factory=dict)
    by_score: dict[str, Bucket] = field(default_factory=dict)
    signals_total: int = 0
    signals_open: int = 0
    signals_pending_result: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    average_planned_rr: float | None = None
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "windowDays": self.window_days,
            "generatedAt": self.generated_at.isoformat(),
            "overall": self.overall.to_dict(),
            "bySymbol": {key: value.to_dict() for key, value in self.by_symbol.items()},
            "byTimeframe": {key: value.to_dict() for key, value in self.by_timeframe.items()},
            "byEntryType": {key: value.to_dict() for key, value in self.by_entry_type.items()},
            "byHour": {key: value.to_dict() for key, value in self.by_hour.items()},
            "byWeekday": {key: value.to_dict() for key, value in self.by_weekday.items()},
            "byScore": {key: value.to_dict() for key, value in self.by_score.items()},
            "signalsTotal": self.signals_total,
            "signalsOpen": self.signals_open,
            "signalsPendingResult": self.signals_pending_result,
            "maxWinStreak": self.max_win_streak,
            "maxLossStreak": self.max_loss_streak,
            "averagePlannedRr": self.average_planned_rr,
            "recommendations": list(self.recommendations),
            "minimumSample": MIN_SAMPLE,
        }


_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def _score_label(score: float) -> str | None:
    for low, high in SCORE_BUCKETS:
        if low <= score < high:
            return f"{low}-{high - 1}"
    return None


def build_report(signals: list[WatcherSignal], window_days: int) -> PerformanceReport:
    """Calcule toutes les statistiques a partir d'une liste de signaux."""
    report = PerformanceReport(window_days=window_days)
    report.signals_total = len(signals)
    report.signals_open = sum(1 for signal in signals if signal.is_open)

    groups: dict[str, dict[str, Bucket]] = {
        "symbol": defaultdict(lambda: Bucket("")),
        "timeframe": defaultdict(lambda: Bucket("")),
        "entry": defaultdict(lambda: Bucket("")),
        "hour": defaultdict(lambda: Bucket("")),
        "weekday": defaultdict(lambda: Bucket("")),
        "score": defaultdict(lambda: Bucket("")),
    }

    planned: list[float] = []
    sequence: list[float] = []

    for signal in sorted(signals, key=lambda item: as_utc(item.created_at) or utcnow()):
        if signal.risk_reward_1:
            planned.append(float(signal.risk_reward_1))
        if signal.result_r is None:
            if not signal.is_open:
                # Clos sans resultat mesurable : signal invalide avant
                # declenchement. Il est compte a part, jamais comme un echec.
                report.signals_pending_result += 1
            continue

        result = float(signal.result_r)
        sequence.append(result)
        report.overall.add(result)
        created = as_utc(signal.created_at) or utcnow()

        _add(groups["symbol"], signal.symbol, result)
        _add(groups["timeframe"], signal.timeframe or "inconnu", result)
        _add(groups["entry"], signal.entry_type.value, result)
        _add(groups["hour"], f"{created.hour:02d}h UTC", result)
        _add(groups["weekday"], _WEEKDAYS[created.weekday()], result)
        label = _score_label(signal.score)
        if label:
            _add(groups["score"], label, result)

    report.by_symbol = dict(groups["symbol"])
    report.by_timeframe = dict(groups["timeframe"])
    report.by_entry_type = dict(groups["entry"])
    report.by_hour = dict(groups["hour"])
    report.by_weekday = dict(groups["weekday"])
    report.by_score = dict(sorted(groups["score"].items()))

    report.max_win_streak, report.max_loss_streak = _streaks(sequence)
    if planned:
        report.average_planned_rr = round(sum(planned) / len(planned), 2)
    report.recommendations = _recommendations(report)
    return report


def _add(group: dict[str, Bucket], key: str, result: float) -> None:
    bucket = group[key]
    if not bucket.label:
        bucket.label = key
    bucket.add(result)


def _streaks(results: list[float]) -> tuple[int, int]:
    """Plus longues series de gains et de pertes consecutifs."""
    best_win = best_loss = current_win = current_loss = 0
    for result in results:
        if result > 0:
            current_win += 1
            current_loss = 0
        elif result < 0:
            current_loss += 1
            current_win = 0
        else:
            current_win = current_loss = 0
        best_win = max(best_win, current_win)
        best_loss = max(best_loss, current_loss)
    return best_win, best_loss


def _recommendations(report: PerformanceReport) -> list[str]:
    """Pistes d'amelioration. Jamais appliquees seules (CDC3 section 41)."""
    notes: list[str] = []
    if not report.overall.significant:
        notes.append(
            f"Echantillon de {report.overall.trades} resultat(s) : trop court pour conclure "
            f"quoi que ce soit (minimum {MIN_SAMPLE})."
        )
        return notes

    for label, bucket in sorted(
        report.by_symbol.items(), key=lambda item: item[1].total_r
    ):
        if bucket.significant and bucket.win_rate is not None and bucket.win_rate < 35:
            notes.append(
                f"{label} : {bucket.win_rate} % de reussite sur {bucket.trades} signaux. "
                "A examiner avant de continuer a le suivre."
            )
    for label, bucket in report.by_score.items():
        if bucket.significant and bucket.win_rate is not None:
            notes.append(
                f"Scores {label} : {bucket.win_rate} % de reussite sur {bucket.trades} signaux "
                f"({bucket.average_r} R en moyenne)."
            )
    if report.overall.profit_factor is not None and report.overall.profit_factor < 1:
        notes.append(
            "Facteur de profit inferieur a 1 sur la periode : les seuils meritent d'etre "
            "releves avant toute autre modification."
        )
    return notes


async def compute(
    session: AsyncSession,
    window_days: int = 30,
    now: datetime | None = None,
    shadow: bool = False,
) -> PerformanceReport:
    """Charge les signaux de la fenetre et en tire le bilan.

    ``shadow`` mesure la bande exploree sous le seuil au lieu de ce qui a
    reellement ete joue. C'est ce bilan qui dit si le seuil merite d'etre
    abaisse, et il ne doit jamais etre confondu avec l'autre.
    """
    moment = now or utcnow()
    since = moment - timedelta(days=max(1, window_days))
    signals = await repository.signals_since(session, since, shadow=shadow)
    return build_report(signals, window_days)


def daily_digest(report: PerformanceReport) -> str:
    """Resume textuel court, utilisable dans un message Telegram."""
    overall = report.overall
    if overall.trades == 0:
        return (
            f"Aucun signal cloture sur les {report.window_days} derniers jours "
            f"({report.signals_open} encore en cours)."
        )
    win_rate = overall.win_rate if overall.win_rate is not None else 0.0
    caveat = "" if overall.significant else " (echantillon encore trop court pour conclure)"
    return (
        f"{overall.trades} signal(aux) cloture(s) sur {report.window_days} jours : "
        f"{overall.wins} gagnant(s), {overall.losses} perdant(s), "
        f"{win_rate} % de reussite, {overall.total_r:+.2f} R cumules{caveat}."
    )


def terminal_statuses() -> tuple[WatcherStatus, ...]:
    """Etats comptes comme clos. Expose pour les tests et l'API."""
    return (
        WatcherStatus.TP3_HIT,
        WatcherStatus.SL_HIT,
        WatcherStatus.INVALIDATED,
        WatcherStatus.EXPIRED,
        WatcherStatus.CANCELLED,
    )


__all__ = [
    "MIN_SAMPLE",
    "SCORE_BUCKETS",
    "Bucket",
    "PerformanceReport",
    "build_report",
    "compute",
    "daily_digest",
    "terminal_statuses",
]
