"""Brique commune des notifications : l'enveloppe et la mise en forme.

Separee des gabarits pour qu'un module qui construit son propre texte (alertes
de mouvement, rapports) n'ait pas a importer les treize gabarits du CDC2.

Regle de presentation : un tiret cadratin remplace une valeur absente, jamais
"None" ni une ligne vide bancale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.intelligence import NotificationCategory, NotificationPriority

DIRECTION_LABELS = {"BUY": "ACHAT", "SELL": "VENTE"}
IMPACT_LABELS = {"LOW": "FAIBLE", "MEDIUM": "MOYEN", "HIGH": "ÉLEVÉ", "CRITICAL": "CRITIQUE"}
ABSENT = "—"


@dataclass(slots=True)
class NotificationDraft:
    """Notification prete a etre enregistree puis poussee."""

    category: NotificationCategory
    priority: NotificationPriority
    title: str
    body: str
    data: dict[str, Any] = field(default_factory=dict)
    symbol: str | None = None
    decision_id: int | None = None
    news_id: int | None = None


def format_direction(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").upper()
    return DIRECTION_LABELS.get(text, text)


def format_impact(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").upper()
    return IMPACT_LABELS.get(text, text)


def format_number(value: Any, digits: int = 2) -> str:
    if value is None:
        return ABSENT
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def format_percent(value: Any, digits: int = 1) -> str:
    if value is None:
        return ABSENT
    try:
        return f"{float(value):.{digits}f} %"
    except (TypeError, ValueError):
        return str(value)


def format_ratio_percent(value: Any) -> str:
    """Une confiance arrive soit en 0..1, soit deja en pourcentage."""
    if value is None:
        return ABSENT
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number <= 1.0:
        number *= 100.0
    return f"{number:.0f} %"


def format_duration(seconds: Any) -> str:
    if seconds is None:
        return ABSENT
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return str(seconds)
    if total < 60:
        return f"{total} s"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {minutes:02d}"
    days, hours = divmod(hours, 24)
    return f"{days} j {hours} h"


def format_moment(moment: datetime | None) -> str:
    return moment.strftime("%d/%m %H:%M UTC") if moment else ABSENT


def labelled_lines(*entries: tuple[str, Any]) -> str:
    """Lignes "Libelle : valeur", les valeurs absentes sont simplement omises."""
    return "\n".join(f"{label} : {value}" for label, value in entries if value not in (None, ""))
