"""Abstraction des fournisseurs d'actualites (CDC2 section 27).

Le moteur ne connait que l'interface ``NewsProvider``. L'implementation
fournie lit des flux RSS ou Atom publics avec ``httpx`` et l'analyseur XML de
la bibliotheque standard : aucune dependance supplementaire.

Regles non negociables :
 - ``robots.txt`` est consulte et respecte ;
 - aucun cookie, aucun jeton, aucune authentification n'est envoye ;
 - un code 401, 402, 403, 407 ou 429 signifie que la source est protegee ou
   limite le trafic : on abandonne proprement, sans jamais tenter de
   contourner la protection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx

from app.config.logging_config import get_logger
from app.models.core import utcnow
from app.services.news.sources import NewsOptions, NewsSource

logger = get_logger(__name__)

# Codes qui signalent une protection : on ne cherche jamais a passer outre.
PROTECTED_STATUS = {401, 402, 403, 407, 429}

# Espaces de noms rencontres dans les flux Atom et RSS enrichis.
_ATOM = "{http://www.w3.org/2005/Atom}"
# RSS 1.0 / RDF : encore utilise par plusieurs sources institutionnelles.
_RSS1 = "{http://purl.org/rss/1.0/}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
_DC = "{http://purl.org/dc/elements/1.1/}"


class NewsProviderError(RuntimeError):
    """La source n'a pas pu etre lue. Le moteur l'ignore et le signale."""


class NewsSourceProtected(NewsProviderError):
    """Source payante, authentifiee ou protegee : elle est laissee de cote."""


@dataclass(slots=True)
class RawNewsItem:
    """Actualite brute, avant toute qualification."""

    source_key: str
    source_name: str
    title: str
    url: str | None = None
    summary: str | None = None
    published_at: datetime | None = None
    received_at: datetime = field(default_factory=utcnow)
    official: bool = False
    category: str | None = None
    countries: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)


class NewsProvider(ABC):
    """Fournisseur d'actualites interchangeable."""

    key: str
    name: str

    @abstractmethod
    async def fetch(self) -> list[RawNewsItem]:
        """Recupere les actualites. Leve ``NewsProviderError`` en cas d'echec."""


class RobotsCache:
    """Memoire des ``robots.txt`` deja lus, par hote.

    Un ``robots.txt`` absent ou illisible vaut autorisation : c'est la regle
    usuelle. Un ``robots.txt`` qui interdit le chemin fait renoncer a la
    source, sans exception.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, RobotFileParser | None] = {}

    def reset(self) -> None:
        self._parsers.clear()

    async def allows(self, client: httpx.AsyncClient, url: str, user_agent: str) -> bool:
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            return False
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = await self._load(client, origin)
        parser = self._parsers[origin]
        if parser is None:
            return True
        return parser.can_fetch(user_agent, url)

    async def _load(self, client: httpx.AsyncClient, origin: str) -> RobotFileParser | None:
        try:
            response = await client.get(f"{origin}/robots.txt")
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("robots.txt injoignable pour %s : %s", origin, exc)
            return None
        if response.status_code >= 400:
            return None
        parser = RobotFileParser()
        try:
            parser.parse(response.text.splitlines())
        except Exception:
            return None
        return parser


def _anciennete(item: RawNewsItem) -> datetime:
    """Date de publication pour le tri. Sans date, la depeche passe en dernier.

    On ne lui invente pas l'heure courante : cela la ferait passer devant des
    depeches reellement fraiches.
    """
    moment = item.published_at
    if moment is None:
        return datetime.min.replace(tzinfo=UTC)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class RssNewsProvider(NewsProvider):
    """Lecteur generique de flux RSS 2.0 et Atom.

    La source est entierement decrite par ``NewsSource`` : rien n'est code en
    dur ici, le meme objet sait lire n'importe quel flux public.
    """

    def __init__(
        self,
        source: NewsSource,
        options: NewsOptions,
        *,
        client: httpx.AsyncClient,
        robots: RobotsCache | None = None,
    ) -> None:
        self.key = source.key
        self.name = source.name
        self._source = source
        self._options = options
        self._client = client
        self._robots = robots

    async def fetch(self) -> list[RawNewsItem]:
        if self._options.respect_robots and self._robots is not None:
            allowed = await self._robots.allows(
                self._client, self._source.url, self._options.user_agent
            )
            if not allowed:
                raise NewsProviderError(
                    "robots.txt interdit la lecture de ce flux : source ignoree"
                )
        try:
            response = await self._client.get(self._source.url)
        except httpx.HTTPError as exc:
            raise NewsProviderError(f"flux injoignable : {exc}") from exc

        if response.status_code in PROTECTED_STATUS:
            raise NewsSourceProtected(
                f"source protegee ou limitee (HTTP {response.status_code}) : aucune tentative "
                "de contournement"
            )
        if response.status_code >= 400:
            raise NewsProviderError(f"reponse HTTP {response.status_code}")

        return self.parse(response.text)

    def parse(self, payload: str) -> list[RawNewsItem]:
        """Analyse le XML du flux. Une entree illisible est simplement sautee."""
        text = payload.strip()
        if _declares_entities(text):
            # Un flux public n'a aucune raison de declarer une DTD ou des
            # entites : refuser evite les attaques XXE et "billion laughs"
            # sans ajouter de dependance a l'analyseur standard.
            raise NewsProviderError("flux XML refuse : declaration DTD ou entite non autorisee")
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as exc:
            raise NewsProviderError(f"flux XML illisible : {exc}") from exc

        # RSS 2.0, puis Atom, puis RSS 1.0 (RDF). Ce dernier place ses
        # articles dans son propre espace de noms : sans cette recherche, le
        # flux etait lu comme VIDE et la source declaree « OK » — une panne
        # silencieuse, la pire espece.
        nodes = root.findall(".//item")
        if not nodes:
            nodes = root.findall(f".//{_ATOM}entry")
        if not nodes:
            nodes = root.findall(f".//{_RSS1}item")
        items: list[RawNewsItem] = []
        for node in nodes:
            item = self._build_item(node)
            if item is not None:
                items.append(item)

        # On trie AVANT de tronquer. Plusieurs flux — Yahoo Finance en
        # particulier — ne rangent pas leurs entrees du plus recent au plus
        # ancien : couper d'abord jetait les depeches fraiches situees en bas
        # du document, et seuls des articles vieux de deux jours arrivaient.
        items.sort(key=_anciennete, reverse=True)
        return items[: self._source.max_items]

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def _build_item(self, node: ElementTree.Element) -> RawNewsItem | None:
        title = _clean(_first_text(node, ("title", f"{_ATOM}title")))
        if not title:
            return None
        return RawNewsItem(
            source_key=self._source.key,
            source_name=self._source.name,
            title=title[:1000],
            url=_extract_link(node),
            summary=_extract_summary(node),
            published_at=_extract_date(node),
            official=self._source.official,
            category=self._source.category,
            countries=list(self._source.countries),
            currencies=list(self._source.currencies),
        )


def _declares_entities(payload: str) -> bool:
    """Detecte une DTD ou une declaration d'entite dans l'en-tete du document."""
    head = payload[:4096].upper()
    return "<!DOCTYPE" in head or "<!ENTITY" in head


def _local_name(tag: str) -> str:
    """Nom de la balise sans son espace de noms."""
    return tag.rsplit("}", 1)[-1]


def _first_text(node: ElementTree.Element, tags: tuple[str, ...]) -> str | None:
    """Texte du premier champ trouve, quel que soit son espace de noms.

    Les noms passes peuvent etre qualifies (« {atom}title ») ou non : seul le
    nom local compte. C'est ce qui permet de lire un flux RSS 1.0, dont tous
    les champs vivent dans un espace de noms propre.
    """
    voulus = [_local_name(tag) for tag in tags]
    for voulu in voulus:
        for child in node:
            if _local_name(child.tag) == voulu and child.text:
                return child.text
    return None


def _extract_link(node: ElementTree.Element) -> str | None:
    """Adresse de l'article, quel que soit le dialecte du flux."""
    liens = [child for child in node if _local_name(child.tag) == "link"]
    for child in liens:
        if child.text and child.text.strip():
            return child.text.strip()[:1024]
    # Atom porte l'adresse dans un attribut plutot que dans le texte.
    for child in liens:
        rel = child.get("rel") or "alternate"
        href = child.get("href")
        if rel == "alternate" and href:
            return href.strip()[:1024]
    for child in node:
        if _local_name(child.tag) == "guid" and child.text:
            valeur = child.text.strip()
            if valeur.startswith("http"):
                return valeur[:1024]
    return None


def _extract_summary(node: ElementTree.Element) -> str | None:
    raw = _first_text(
        node,
        (
            "description",
            f"{_ATOM}summary",
            f"{_ATOM}content",
            f"{_CONTENT}encoded",
        ),
    )
    summary = _clean(raw)
    return summary[:2000] if summary else None


def _extract_date(node: ElementTree.Element) -> datetime | None:
    raw = _first_text(
        node,
        (
            "pubDate",
            f"{_ATOM}published",
            f"{_ATOM}updated",
            f"{_DC}date",
            "date",
        ),
    )
    return parse_feed_date(raw)


def parse_feed_date(raw: str | None) -> datetime | None:
    """Convertit une date de flux en UTC (CDC2 section 79).

    RSS utilise le format RFC 822, Atom le format ISO 8601. Une date absente
    ou incomprehensible reste ``None`` : on n'invente jamais un horodatage.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        iso = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clean(raw: str | None) -> str | None:
    """Retire les balises HTML residuelles et normalise les espaces."""
    if raw is None:
        return None
    text = raw.replace("<![CDATA[", "").replace("]]>", "")
    out: list[str] = []
    depth = 0
    for char in text:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(char)
    cleaned = " ".join("".join(out).split())
    return cleaned or None


def build_client(options: NewsOptions, *, transport: Any = None) -> httpx.AsyncClient:
    """Client HTTP de collecte : identite claire, aucune authentification.

    ``transport`` permet aux tests de brancher un ``httpx.MockTransport`` et
    donc de ne jamais toucher au reseau.
    """
    kwargs: dict[str, Any] = {
        "timeout": options.timeout_seconds,
        "follow_redirects": True,
        "headers": {
            "User-Agent": options.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        },
    }
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.AsyncClient(**kwargs)


__all__ = [
    "PROTECTED_STATUS",
    "NewsProvider",
    "NewsProviderError",
    "NewsSourceProtected",
    "RawNewsItem",
    "RobotsCache",
    "RssNewsProvider",
    "build_client",
    "parse_feed_date",
]
