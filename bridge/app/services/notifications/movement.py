"""Alertes de mouvement de marche (CDC2 section 65).

Six familles de mouvements sont reconnues : volatilite soudaine, pic de spread,
gap, grande bougie, cassure (breakout) et mouvement anormal.

La detection est une fonction pure : elle prend des mesures deja calculees par
le scanner de marche et rend une liste d'alertes. Rien n'est lu en base, rien
n'est appele sur le reseau, donc elle se teste sans aucune dependance.

Le scanner (autre chantier) appelle ``evaluate_market_movement`` : c'est le seul
point de contact entre ``market_scanner`` et les notifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import (
    NotificationCategory,
    NotificationEvent,
    NotificationPriority,
)
from app.services.notifications.formatting import (
    NotificationDraft,
    format_number,
    format_percent,
)

MOVEMENT_ABNORMAL = "ABNORMAL_MOVE"
MOVEMENT_VOLATILITY = "SUDDEN_VOLATILITY"
MOVEMENT_SPREAD = "SPREAD_SPIKE"
MOVEMENT_GAP = "GAP"
MOVEMENT_LARGE_CANDLE = "LARGE_CANDLE"
MOVEMENT_BREAKOUT = "BREAKOUT"

MOVEMENT_TITLES: dict[str, str] = {
    MOVEMENT_ABNORMAL: "⚡ MOUVEMENT ANORMAL",
    MOVEMENT_VOLATILITY: "📊 VOLATILITÉ SOUDAINE",
    MOVEMENT_SPREAD: "↔️ SPREAD ANORMAL",
    MOVEMENT_GAP: "🕳 GAP D’OUVERTURE",
    MOVEMENT_LARGE_CANDLE: "🕯 GRANDE BOUGIE",
    MOVEMENT_BREAKOUT: "🚀 CASSURE DE NIVEAU",
}


@dataclass(frozen=True, slots=True)
class MovementThresholds:
    """Seuils de declenchement, ajustables par le scanner s'il le souhaite."""

    move_percent: float = 0.8
    volatility_ratio: float = 2.0
    spread_ratio: float = 3.0
    gap_percent: float = 0.5
    candle_atr_ratio: float = 2.0


@dataclass(frozen=True, slots=True)
class MovementAlert:
    """Un mouvement detecte, deja traduit en texte lisible."""

    kind: str
    symbol: str
    priority: NotificationPriority
    headline: str
    details: list[str]

    def to_draft(self) -> NotificationDraft:
        body = "\n".join([self.symbol, "", self.headline, *self.details])
        return NotificationDraft(
            category=NotificationCategory.OPPORTUNITY,
            priority=self.priority,
            title=f"{MOVEMENT_TITLES.get(self.kind, '⚡ MOUVEMENT')} — {self.symbol}",
            body=body,
            data={"route": "market", "symbol": self.symbol, "movement": self.kind},
            symbol=self.symbol,
        )


DEFAULT_THRESHOLDS = MovementThresholds()


def detect_movements(
    symbol: str,
    *,
    change_percent: float | None = None,
    window_minutes: int | None = None,
    volatility_ratio: float | None = None,
    spread_points: float | None = None,
    average_spread_points: float | None = None,
    gap_percent: float | None = None,
    candle_range: float | None = None,
    atr: float | None = None,
    breakout_level: float | None = None,
    breakout_direction: str | None = None,
    thresholds: MovementThresholds = DEFAULT_THRESHOLDS,
    digits: int = 2,
) -> list[MovementAlert]:
    """Traduit des mesures de marche en alertes. Fonction pure et testable."""
    alerts: list[MovementAlert] = []

    if change_percent is not None and abs(change_percent) >= thresholds.move_percent:
        window = f" en {window_minutes} min" if window_minutes else ""
        details = []
        if volatility_ratio:
            details.append(f"Volatilité : {volatility_ratio:.1f}x la normale")
        alerts.append(
            MovementAlert(
                kind=MOVEMENT_ABNORMAL,
                symbol=symbol,
                priority=_priority_for(abs(change_percent), thresholds.move_percent),
                headline=f"{change_percent:+.2f} %{window}",
                details=details,
            )
        )

    if volatility_ratio is not None and volatility_ratio >= thresholds.volatility_ratio:
        alerts.append(
            MovementAlert(
                kind=MOVEMENT_VOLATILITY,
                symbol=symbol,
                priority=_priority_for(volatility_ratio, thresholds.volatility_ratio),
                headline=f"Volatilité {volatility_ratio:.1f}x la normale",
                details=[f"Variation : {format_percent(change_percent, 2)}"] if change_percent else [],
            )
        )

    if spread_points is not None and average_spread_points:
        ratio = spread_points / average_spread_points if average_spread_points else 0.0
        if ratio >= thresholds.spread_ratio:
            alerts.append(
                MovementAlert(
                    kind=MOVEMENT_SPREAD,
                    symbol=symbol,
                    priority=NotificationPriority.HIGH,
                    headline=f"Spread {ratio:.1f}x la moyenne",
                    details=[
                        f"Spread actuel : {format_number(spread_points, 1)} points",
                        f"Moyenne : {format_number(average_spread_points, 1)} points",
                        "Exécution déconseillée tant que le spread reste large.",
                    ],
                )
            )

    if gap_percent is not None and abs(gap_percent) >= thresholds.gap_percent:
        alerts.append(
            MovementAlert(
                kind=MOVEMENT_GAP,
                symbol=symbol,
                priority=_priority_for(abs(gap_percent), thresholds.gap_percent),
                headline=f"Gap de {gap_percent:+.2f} % à l’ouverture",
                details=["Les niveaux des signaux en attente peuvent être dépassés."],
            )
        )

    if candle_range is not None and atr:
        ratio = candle_range / atr if atr else 0.0
        if ratio >= thresholds.candle_atr_ratio:
            alerts.append(
                MovementAlert(
                    kind=MOVEMENT_LARGE_CANDLE,
                    symbol=symbol,
                    priority=_priority_for(ratio, thresholds.candle_atr_ratio),
                    headline=f"Bougie {ratio:.1f}x l’ATR",
                    details=[f"Amplitude : {format_number(candle_range, digits)}"],
                )
            )

    if breakout_level is not None and breakout_direction:
        way = "au-dessus de" if str(breakout_direction).upper() in {"UP", "BUY"} else "sous"
        alerts.append(
            MovementAlert(
                kind=MOVEMENT_BREAKOUT,
                symbol=symbol,
                priority=NotificationPriority.HIGH,
                headline=f"Cassure {way} {format_number(breakout_level, digits)}",
                details=[f"Variation : {format_percent(change_percent, 2)}"] if change_percent else [],
            )
        )

    return alerts


def _priority_for(value: float, threshold: float) -> NotificationPriority:
    """Deux fois le seuil : c'est critique. Sinon c'est important."""
    if threshold > 0 and value >= threshold * 2:
        return NotificationPriority.CRITICAL
    return NotificationPriority.HIGH


async def evaluate_market_movement(
    symbol: str,
    *,
    change_percent: float | None = None,
    window_minutes: int | None = None,
    volatility_ratio: float | None = None,
    spread_points: float | None = None,
    average_spread_points: float | None = None,
    gap_percent: float | None = None,
    candle_range: float | None = None,
    atr: float | None = None,
    breakout_level: float | None = None,
    breakout_direction: str | None = None,
    thresholds: MovementThresholds = DEFAULT_THRESHOLDS,
    digits: int = 2,
    session: AsyncSession | None = None,
    notify: bool = True,
) -> list[NotificationEvent]:
    """Point d'entree du scanner de marche.

    Detecte les mouvements puis, si ``notify`` est vrai, les envoie via le
    NotificationService (anti-doublon et plages de silence compris). Renvoie les
    notifications reellement enregistrees.
    """
    alerts = detect_movements(
        symbol,
        change_percent=change_percent,
        window_minutes=window_minutes,
        volatility_ratio=volatility_ratio,
        spread_points=spread_points,
        average_spread_points=average_spread_points,
        gap_percent=gap_percent,
        candle_range=candle_range,
        atr=atr,
        breakout_level=breakout_level,
        breakout_direction=breakout_direction,
        thresholds=thresholds,
        digits=digits,
    )
    if not alerts or not notify:
        return []

    from app.services.notifications.service import notification_service

    return await notification_service.send_many(
        [alert.to_draft() for alert in alerts], session=session
    )


def movement_summary(alerts: list[MovementAlert]) -> dict[str, Any]:
    """Resume compact, utile au diagnostic du scanner."""
    return {
        "count": len(alerts),
        "kinds": [alert.kind for alert in alerts],
        "symbols": sorted({alert.symbol for alert in alerts}),
    }
