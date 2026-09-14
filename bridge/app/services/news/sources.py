"""Sources d'actualites configurables (CDC2 section 27).

Aucune source n'est codee en dur dans la logique : le moteur lit cette
configuration, l'utilisateur peut l'editer via l'API. La liste livree par
defaut ne contient que des flux publics, librement accessibles, publies par
des institutions ou des medias financiers qui les mettent volontairement a
disposition.

Interdiction absolue (CDC2 section 27) : ne jamais contourner un paywall, un
CAPTCHA, une authentification ou une protection anti-bot. Une source qui
repond 401, 402, 403 ou 429 est simplement ignoree, et signalee comme telle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import settings_repo

# Cles de configuration stockees dans la table ``settings``.
SOURCES_KEY = "news.sources"
OPTIONS_KEY = "news.options"

# Identite annoncee aux serveurs : honnete, joignable, jamais deguisee.
DEFAULT_USER_AGENT = "TradePilotBridge/1.0 (flux RSS publics)"


@dataclass(slots=True)
class NewsSource:
    """Un flux RSS ou Atom public.

    ``official`` distingue une source primaire (banque centrale, institut
    statistique, regulateur) d'un media : une source primaire pese plus lourd
    dans la verification (CDC2 section 32).
    """

    key: str
    name: str
    url: str
    enabled: bool = True
    official: bool = False
    category: str | None = None
    countries: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    max_items: int = 30

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> NewsSource | None:
        """Construit une source depuis un dictionnaire non fiable.

        Retourne ``None`` si l'entree est inexploitable : on prefere ignorer
        une ligne de configuration abimee plutot que d'inventer une source.
        """
        key = str(raw.get("key") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not key or not url:
            return None
        if not url.lower().startswith(("http://", "https://")):
            return None
        countries = [str(c).upper()[:8] for c in raw.get("countries") or [] if str(c).strip()]
        currencies = [str(c).upper()[:8] for c in raw.get("currencies") or [] if str(c).strip()]
        try:
            max_items = int(raw.get("max_items") or raw.get("maxItems") or 30)
        except (TypeError, ValueError):
            max_items = 30
        return cls(
            key=key[:64],
            name=str(raw.get("name") or key)[:128],
            url=url[:1024],
            enabled=bool(raw.get("enabled", True)),
            official=bool(raw.get("official", False)),
            category=(str(raw["category"])[:64] if raw.get("category") else None),
            countries=countries,
            currencies=currencies,
            max_items=max(1, min(max_items, 200)),
        )


@dataclass(slots=True)
class NewsOptions:
    """Reglages de collecte, eux aussi modifiables par l'utilisateur."""

    user_agent: str = DEFAULT_USER_AGENT
    respect_robots: bool = True
    timeout_seconds: float = 15.0
    dedup_window_hours: int = 72
    similarity_threshold: float = 0.72

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> NewsOptions:
        base = cls()
        if not isinstance(raw, dict):
            return base
        agent = str(raw.get("user_agent") or raw.get("userAgent") or base.user_agent)
        timeout = _as_float(raw, ("timeout_seconds", "timeoutSeconds"), base.timeout_seconds)
        window = _as_int(raw, ("dedup_window_hours", "dedupWindowHours"), base.dedup_window_hours)
        threshold = _as_float(
            raw, ("similarity_threshold", "similarityThreshold"), base.similarity_threshold
        )
        return cls(
            user_agent=agent[:200] or base.user_agent,
            respect_robots=bool(raw.get("respect_robots", raw.get("respectRobots", True))),
            timeout_seconds=max(2.0, min(timeout, 60.0)),
            dedup_window_hours=max(1, min(window, 720)),
            similarity_threshold=max(0.4, min(threshold, 0.99)),
        )


def _as_float(raw: dict[str, Any], keys: tuple[str, ...], fallback: float) -> float:
    for key in keys:
        if key in raw:
            try:
                return float(raw[key])
            except (TypeError, ValueError):
                return fallback
    return fallback


def _as_int(raw: dict[str, Any], keys: tuple[str, ...], fallback: int) -> int:
    for key in keys:
        if key in raw:
            try:
                return int(raw[key])
            except (TypeError, ValueError):
                return fallback
    return fallback


# ---------------------------------------------------------------------------
# Choix retenus : d'abord les sources primaires (banques centrales, instituts
# statistiques, regulateurs, agence de l'energie), car elles publient les
# chiffres elles-memes et ne dependent d'aucune interpretation. Elles sont
# lentes par nature — une banque centrale ne communique pas toutes les heures.
#
# Viennent ensuite des medias financiers a flux ouvert, qui apportent la
# reactivite et la confirmation multi sources exigee par le CDC2 section 32.
#
# Chaque flux a ete retenu sur mesure, pas sur reputation : age reel de son
# article le plus recent, mediane de ses articles, et robots.txt autorisant la
# lecture. Trois sources ont ete retirees pour cette raison :
#   - Yahoo Finance : articles vieux d'un jour et demi ;
#   - US Bureau of Economic Analysis : mediane des articles superieure a un an ;
#   - Banque des reglements internationaux : aucune date d'article lisible.
# Google Actualites, le plus reactif, est ecarte : son robots.txt l'interdit.
# Aucun flux reserve aux abonnes.

DEFAULT_SOURCES: tuple[NewsSource, ...] = (
    # --- sources primaires -------------------------------------------------
    NewsSource(
        key="fed_press",
        name="Federal Reserve - communiques",
        url="https://www.federalreserve.gov/feeds/press_all.xml",
        official=True,
        category="central_bank",
        countries=["US"],
        currencies=["USD"],
    ),
    NewsSource(
        key="ecb_press",
        name="Banque centrale europeenne - communiques",
        url="https://www.ecb.europa.eu/rss/press.html",
        official=True,
        category="central_bank",
        countries=["EU"],
        currencies=["EUR"],
    ),
    NewsSource(
        key="boe_news",
        name="Bank of England - actualites",
        url="https://www.bankofengland.co.uk/rss/news",
        official=True,
        category="central_bank",
        countries=["GB"],
        currencies=["GBP"],
    ),
    NewsSource(
        key="boj_news",
        name="Banque du Japon - nouveautes",
        url="https://www.boj.or.jp/en/rss/whatsnew.xml",
        official=True,
        category="central_bank",
        countries=["JP"],
        currencies=["JPY"],
    ),
    NewsSource(
        key="bls_releases",
        name="US Bureau of Labor Statistics",
        url="https://www.bls.gov/feed/bls_latest.rss",
        official=True,
        category="statistics",
        countries=["US"],
        currencies=["USD"],
    ),
    NewsSource(
        key="sec_press",
        name="SEC - communiques",
        url="https://www.sec.gov/news/pressreleases.rss",
        official=True,
        category="regulation",
        countries=["US"],
        currencies=["USD"],
    ),
    NewsSource(
        key="eia_energy",
        name="US Energy Information Administration",
        url="https://www.eia.gov/rss/todayinenergy.xml",
        official=True,
        category="energy",
        countries=["US"],
        currencies=["USD"],
    ),
    # --- medias financiers, pour la reactivite -----------------------------
    NewsSource(
        key="fxstreet_news",
        name="FXStreet - actualites",
        url="https://www.fxstreet.com/rss/news",
        category="markets",
        countries=["WORLD"],
    ),
    NewsSource(
        key="investing_news",
        name="Investing.com - actualites",
        url="https://www.investing.com/rss/news.rss",
        category="markets",
        countries=["WORLD"],
    ),
    NewsSource(
        key="investing_economy",
        name="Investing.com - economie",
        url="https://www.investing.com/rss/news_14.rss",
        category="macro",
        countries=["WORLD"],
    ),
    NewsSource(
        key="forexlive_news",
        name="ForexLive",
        url="https://www.forexlive.com/feed/news",
        category="markets",
        countries=["WORLD"],
    ),
    NewsSource(
        key="cnbc_top",
        name="CNBC - a la une",
        url="https://www.cnbc.com/id/100003114/device/rss/rss.html",
        category="markets",
        countries=["US"],
    ),
    NewsSource(
        key="marketwatch_top",
        name="MarketWatch - a la une",
        url="https://feeds.content.dowjones.io/public/rss/mw_topstories",
        category="markets",
        countries=["US"],
    ),
    NewsSource(
        key="nasdaq_markets",
        name="Nasdaq - marches",
        url="https://www.nasdaq.com/feed/rssoutbound?category=Markets",
        category="markets",
        countries=["US"],
    ),
    NewsSource(
        key="oilprice_main",
        name="OilPrice - energie",
        url="https://oilprice.com/rss/main",
        category="energy",
        countries=["WORLD"],
    ),
    NewsSource(
        key="coindesk_news",
        name="CoinDesk - crypto",
        url="https://www.coindesk.com/arc/outboundfeeds/rss/",
        category="crypto",
        countries=["WORLD"],
    ),
)


def default_sources() -> list[NewsSource]:
    """Copie modifiable de la liste par defaut."""
    return [
        NewsSource(
            key=source.key,
            name=source.name,
            url=source.url,
            enabled=source.enabled,
            official=source.official,
            category=source.category,
            countries=list(source.countries),
            currencies=list(source.currencies),
            max_items=source.max_items,
        )
        for source in DEFAULT_SOURCES
    ]


async def load_sources(session: AsyncSession) -> list[NewsSource]:
    """Sources configurees, ou la liste par defaut si rien n'a ete enregistre."""
    stored = await settings_repo.get_setting(session, SOURCES_KEY, None)
    if not isinstance(stored, list):
        return default_sources()
    parsed = (NewsSource.from_dict(raw) for raw in stored if isinstance(raw, dict))
    sources = [source for source in parsed if source is not None]
    return sources or default_sources()


async def save_sources(session: AsyncSession, sources: list[NewsSource]) -> list[NewsSource]:
    """Remplace la configuration des flux. Les cles en double sont fusionnees."""
    unique: dict[str, NewsSource] = {}
    for source in sources:
        unique[source.key] = source
    ordered = list(unique.values())
    await settings_repo.set_setting(session, SOURCES_KEY, [s.to_dict() for s in ordered])
    return ordered


async def load_options(session: AsyncSession) -> NewsOptions:
    stored = await settings_repo.get_setting(session, OPTIONS_KEY, None)
    return NewsOptions.from_dict(stored if isinstance(stored, dict) else {})


async def save_options(session: AsyncSession, options: NewsOptions) -> NewsOptions:
    await settings_repo.set_setting(session, OPTIONS_KEY, options.to_dict())
    return options


__all__ = [
    "DEFAULT_SOURCES",
    "DEFAULT_USER_AGENT",
    "OPTIONS_KEY",
    "SOURCES_KEY",
    "NewsOptions",
    "NewsSource",
    "default_sources",
    "load_options",
    "load_sources",
    "save_options",
    "save_sources",
]
