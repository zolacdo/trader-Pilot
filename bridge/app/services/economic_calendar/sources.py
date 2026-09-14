"""Sources du calendrier economique (CDC2 section 33).

Aucune source n'est livree par defaut, et c'est volontaire : il n'existe pas
de flux de calendrier economique a la fois public, stable et libre de droits
que l'on puisse activer sans l'accord de l'utilisateur. Tant qu'aucune source
n'est configuree, le moteur le dit clairement plutot que d'afficher des
evenements inventes.

Le fournisseur fourni lit un point d'acces JSON decrit entierement par la
configuration : chemin de la liste, nom des champs, format des dates. Il sait
donc s'adapter a la source que l'utilisateur choisit, sans code specifique.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import settings_repo

CALENDAR_SOURCES_KEY = "economic_calendar.sources"
CALENDAR_OPTIONS_KEY = "economic_calendar.options"

# Correspondance par defaut entre les champs attendus et ceux d'une source.
DEFAULT_FIELD_MAP: dict[str, str] = {
    "external_id": "id",
    "scheduled_at": "date",
    "title": "title",
    "country": "country",
    "currency": "currency",
    "impact": "impact",
    "forecast": "forecast",
    "previous": "previous",
    "actual": "actual",
}

# Valeurs d'importance rencontrees chez les fournisseurs, ramenees aux trois
# niveaux du CDC2 section 33.
DEFAULT_IMPACT_MAP: dict[str, str] = {
    "1": "LOW",
    "2": "MEDIUM",
    "3": "HIGH",
    "low": "LOW",
    "medium": "MEDIUM",
    "moderate": "MEDIUM",
    "high": "HIGH",
    "holiday": "LOW",
    "faible": "LOW",
    "moyen": "MEDIUM",
    "eleve": "HIGH",
}


@dataclass(slots=True)
class CalendarSource:
    """Point d'acces JSON decrivant un calendrier economique."""

    key: str
    name: str
    url: str
    enabled: bool = True
    items_path: str = ""
    field_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_FIELD_MAP))
    impact_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_IMPACT_MAP))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CalendarSource | None:
        key = str(raw.get("key") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not key or not url.lower().startswith(("http://", "https://")):
            return None
        field_map = dict(DEFAULT_FIELD_MAP)
        raw_map = raw.get("field_map") or raw.get("fieldMap")
        if isinstance(raw_map, dict):
            for name, source_field in raw_map.items():
                # Une chaine vide signifie « cette source ne fournit pas ce
                # champ » : sans cela, on ne pourrait pas desactiver une
                # correspondance par defaut, et un flux qui range la devise
                # dans « country » remplirait le pays avec « AUD ».
                if isinstance(name, str) and isinstance(source_field, str):
                    field_map[name] = source_field
        impact_map = dict(DEFAULT_IMPACT_MAP)
        raw_impact = raw.get("impact_map") or raw.get("impactMap")
        if isinstance(raw_impact, dict):
            for name, level in raw_impact.items():
                if isinstance(name, str) and isinstance(level, str):
                    impact_map[name.strip().lower()] = level.strip().upper()
        return cls(
            key=key[:64],
            name=str(raw.get("name") or key)[:128],
            url=url[:1024],
            enabled=bool(raw.get("enabled", True)),
            items_path=str(raw.get("items_path") or raw.get("itemsPath") or "")[:128],
            field_map=field_map,
            impact_map=impact_map,
        )


@dataclass(slots=True)
class CalendarOptions:
    """Reglages du calendrier, tous modifiables."""

    user_agent: str = "TradePilotBridge/1.0 (calendrier economique)"
    timeout_seconds: float = 15.0
    notify_offsets: list[int] = field(default_factory=lambda: [60, 30, 15, 5])
    notify_minimum_impact: str = "HIGH"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> CalendarOptions:
        base = cls()
        if not isinstance(raw, dict):
            return base
        try:
            timeout = float(raw.get("timeout_seconds", raw.get("timeoutSeconds", base.timeout_seconds)))
        except (TypeError, ValueError):
            timeout = base.timeout_seconds
        offsets = base.notify_offsets
        raw_offsets = raw.get("notify_offsets", raw.get("notifyOffsets"))
        if isinstance(raw_offsets, list):
            parsed = []
            for entry in raw_offsets:
                try:
                    value = int(entry)
                except (TypeError, ValueError):
                    continue
                if 0 < value <= 1440:
                    parsed.append(value)
            if parsed:
                offsets = sorted(set(parsed), reverse=True)
        impact = raw.get("notify_minimum_impact", raw.get("notifyMinimumImpact"))
        minimum = base.notify_minimum_impact
        if isinstance(impact, str) and impact.strip():
            minimum = impact.strip().upper()
        return cls(
            user_agent=str(raw.get("user_agent") or raw.get("userAgent") or base.user_agent)[:200],
            timeout_seconds=max(2.0, min(timeout, 60.0)),
            notify_offsets=offsets,
            notify_minimum_impact=minimum,
        )


async def load_sources(session: AsyncSession) -> list[CalendarSource]:
    """Sources configurees. Liste vide tant que l'utilisateur n'en ajoute pas."""
    stored = await settings_repo.get_setting(session, CALENDAR_SOURCES_KEY, None)
    if not isinstance(stored, list):
        return []
    parsed = (CalendarSource.from_dict(raw) for raw in stored if isinstance(raw, dict))
    return [source for source in parsed if source is not None]


async def save_sources(
    session: AsyncSession, sources: list[CalendarSource]
) -> list[CalendarSource]:
    unique: dict[str, CalendarSource] = {source.key: source for source in sources}
    ordered = list(unique.values())
    await settings_repo.set_setting(
        session, CALENDAR_SOURCES_KEY, [source.to_dict() for source in ordered]
    )
    return ordered


async def load_options(session: AsyncSession) -> CalendarOptions:
    stored = await settings_repo.get_setting(session, CALENDAR_OPTIONS_KEY, None)
    return CalendarOptions.from_dict(stored)


async def save_options(session: AsyncSession, options: CalendarOptions) -> CalendarOptions:
    await settings_repo.set_setting(session, CALENDAR_OPTIONS_KEY, options.to_dict())
    return options


__all__ = [
    "CALENDAR_OPTIONS_KEY",
    "CALENDAR_SOURCES_KEY",
    "DEFAULT_FIELD_MAP",
    "DEFAULT_IMPACT_MAP",
    "CalendarOptions",
    "CalendarSource",
    "load_options",
    "load_sources",
    "save_options",
    "save_sources",
]
