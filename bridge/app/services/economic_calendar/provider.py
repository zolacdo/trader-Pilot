"""Lecture d'un calendrier economique JSON configurable (CDC2 section 33).

Le fournisseur ne connait aucun format particulier : la configuration lui dit
ou trouver la liste et comment s'appellent les champs. Un champ absent reste
``None`` ; un evenement sans date ou sans intitule est ignore. Aucune valeur
n'est inventee.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config.logging_config import get_logger
from app.models.intelligence import NewsImpact
from app.services.economic_calendar.sources import CalendarOptions, CalendarSource

logger = get_logger(__name__)

PROTECTED_STATUS = {401, 402, 403, 407, 429}


def _stable_id(title: str, scheduled: datetime) -> str:
    """Identifiant reproductible pour une source qui n'en fournit aucun.

    L'empreinte retient l'intitule et le JOUR, pas l'heure exacte. Un
    evenement decale de quelques minutes — cela arrive couramment — garderait
    sinon une nouvelle identite : l'ancienne ligne resterait en base avec ses
    rappels deja envoyes, et continuerait d'annoncer une heure perimee.
    """
    jour = scheduled.astimezone(UTC).date().isoformat()
    empreinte = f"{title.strip().lower()}|{jour}"
    return hashlib.sha256(empreinte.encode("utf-8")).hexdigest()[:32]


class CalendarProviderError(RuntimeError):
    """La source n'a pas pu etre lue : elle est ignoree, pas contournee."""


@dataclass(slots=True)
class RawEconomicEvent:
    """Evenement brut, tel que la source le fournit."""

    external_id: str
    scheduled_at: datetime
    title: str
    country: str | None = None
    currency: str | None = None
    impact: NewsImpact = NewsImpact.LOW
    forecast: str | None = None
    previous: str | None = None
    actual: str | None = None


class JsonCalendarProvider:
    """Lit un point d'acces JSON decrit par ``CalendarSource``."""

    def __init__(
        self, source: CalendarSource, options: CalendarOptions, *, client: httpx.AsyncClient
    ) -> None:
        self.key = source.key
        self.name = source.name
        self._source = source
        self._options = options
        self._client = client

    async def fetch(self) -> list[RawEconomicEvent]:
        try:
            response = await self._client.get(self._source.url)
        except httpx.HTTPError as exc:
            raise CalendarProviderError(f"calendrier injoignable : {exc}") from exc
        if response.status_code in PROTECTED_STATUS:
            raise CalendarProviderError(
                f"source protegee ou limitee (HTTP {response.status_code}) : aucune tentative "
                "de contournement"
            )
        if response.status_code >= 400:
            raise CalendarProviderError(f"reponse HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CalendarProviderError(f"reponse JSON illisible : {exc}") from exc
        return self.parse(payload)

    def parse(self, payload: Any) -> list[RawEconomicEvent]:
        """Extrait les evenements exploitables. Les autres sont sautes."""
        rows = self._locate_rows(payload)
        events: list[RawEconomicEvent] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            event = self._build(row, index)
            if event is not None:
                events.append(event)
        return events

    def _locate_rows(self, payload: Any) -> list[Any]:
        node = payload
        if self._source.items_path:
            for segment in self._source.items_path.split("."):
                if not segment:
                    continue
                if not isinstance(node, dict) or segment not in node:
                    raise CalendarProviderError(
                        f"chemin '{self._source.items_path}' absent de la reponse"
                    )
                node = node[segment]
        if isinstance(node, list):
            return node
        raise CalendarProviderError("la reponse ne contient pas de liste d'evenements")

    def _field(self, row: dict[str, Any], name: str, defaut: str) -> Any:
        """Valeur brute d'un champ, ou ``None`` s'il est declare absent."""
        source_field = self._source.field_map.get(name, defaut)
        if not source_field:
            return None
        return row.get(source_field)

    def _build(self, row: dict[str, Any], index: int) -> RawEconomicEvent | None:
        title = _text(self._field(row, "title", "title"))
        scheduled = parse_datetime(self._field(row, "scheduled_at", "date"))
        if not title or scheduled is None:
            return None
        raw_id = _text(self._field(row, "external_id", "id"))
        # Sans identifiant fourni, on en derive un a partir de l'intitule et de
        # l'horaire. Se rabattre sur la position dans la liste serait instable :
        # un calendrier hebdomadaire perd ses evenements passes au fil des
        # jours, et chaque rafraichissement recreerait les memes evenements
        # sous un nouvel identifiant.
        external_id = raw_id or _stable_id(title, scheduled)
        return RawEconomicEvent(
            external_id=f"{self._source.key}:{external_id}"[:128],
            scheduled_at=scheduled,
            title=title[:255],
            country=_upper(self._field(row, "country", "country"), 8),
            currency=_upper(self._field(row, "currency", "currency"), 8),
            impact=self._impact(self._field(row, "impact", "impact")),
            forecast=_text(self._field(row, "forecast", "forecast"), 64),
            previous=_text(self._field(row, "previous", "previous"), 64),
            actual=_text(self._field(row, "actual", "actual"), 64),
        )

    def _impact(self, value: Any) -> NewsImpact:
        """Importance normalisee. Inconnue vaut LOW, jamais davantage."""
        if value is None:
            return NewsImpact.LOW
        key = str(value).strip().lower()
        mapped = self._source.impact_map.get(key)
        if mapped is None:
            return NewsImpact.LOW
        try:
            return NewsImpact(mapped)
        except ValueError:
            return NewsImpact.LOW


def parse_datetime(value: Any) -> datetime | None:
    """Date d'evenement ramenee en UTC (CDC2 section 79).

    Accepte un horodatage Unix ou une chaine ISO 8601. Une date sans fuseau
    est consideree comme deja exprimee en UTC : c'est la convention interne.
    """
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) >= 9:
        try:
            return datetime.fromtimestamp(int(text), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _text(value: Any, limit: int = 255) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _upper(value: Any, limit: int) -> str | None:
    text = _text(value, limit)
    return text.upper() if text else None


def build_client(options: CalendarOptions, *, transport: Any = None) -> httpx.AsyncClient:
    """Client HTTP du calendrier. ``transport`` permet de tester hors reseau."""
    kwargs: dict[str, Any] = {
        "timeout": options.timeout_seconds,
        "follow_redirects": True,
        "headers": {"User-Agent": options.user_agent, "Accept": "application/json"},
    }
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.AsyncClient(**kwargs)


__all__ = [
    "CalendarProviderError",
    "JsonCalendarProvider",
    "RawEconomicEvent",
    "build_client",
    "parse_datetime",
]
