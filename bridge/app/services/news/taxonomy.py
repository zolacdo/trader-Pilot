"""Vocabulaire deterministe du moteur d'actualites (CDC2 sections 28 et 30).

Ce module ne contient que des listes de mots et des correspondances. Il sert
au prefiltre : c'est lui qui doit traiter la majorite des nouvelles, sans
aucune intelligence artificielle. Rien n'est devine ici : un mot present
declenche une correspondance, un mot absent n'en declenche aucune.
"""

from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Minuscule, sans accent, sans ponctuation : forme comparable."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in folded if not unicodedata.combining(c))
    lowered = _NON_WORD.sub(" ", ascii_text.lower())
    return _SPACES.sub(" ", lowered).strip()


# ---------------------------------------------------------------------------
# Categories (CDC2 section 28)
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "central_bank": (
        "fomc", "federal reserve", "fed ", "ecb", "bce", "european central bank",
        "bank of england", "boe ", "bank of japan", "boj ", "snb", "rba", "boc",
        "rate decision", "interest rate", "monetary policy", "taux directeur",
        "rate cut", "rate hike", "quantitative easing", "tapering", "powell",
        "lagarde", "bailey", "ueda", "central banker", "banque centrale",
    ),
    "inflation": (
        "cpi", "ppi", "inflation", "core inflation", "consumer price",
        "producer price", "pce", "deflation", "prix a la consommation",
    ),
    "employment": (
        "nfp", "non farm payrolls", "nonfarm payrolls", "unemployment",
        "jobless claims", "employment report", "payrolls", "chomage", "emploi",
        "labor market", "adp employment",
    ),
    "growth": (
        "gdp", "pib", "gross domestic product", "recession", "retail sales",
        "industrial production", "pmi", "ism ", "consumer confidence",
    ),
    "geopolitics": (
        # « war » seul se declenche sur « price war » ou « bidding war », qui
        # relevent du commerce et non de la geopolitique : on exige un
        # qualificatif.
        "war in", "war with", "at war", "civil war", "guerre en", "guerre civile",
        "conflict", "conflit", "invasion", "missile", "strike on",
        "sanction", "sanctions", "embargo", "ceasefire", "military",
        "geopolitical", "geopolitique", "coup ", "terrorist", "terroriste",
    ),
    "energy": (
        "opec", "opep", "crude", "oil price", "petrole", "brent", "wti",
        "natural gas", "gaz naturel", "energy crisis", "refinery", "pipeline",
        "barrel", "production cut",
    ),
    "regulation": (
        "regulation", "regulatory", "sec charges", "lawsuit", "antitrust",
        "ban on", "legislation", "bill passed", "tariff", "tarif douanier",
        "trade deal", "export controls",
    ),
    "crisis": (
        "bank failure", "bankruptcy", "faillite", "default", "defaut de paiement",
        "bailout", "credit crunch", "financial crisis", "crise financiere",
        "liquidity crisis", "bank run", "contagion",
    ),
    "corporate": (
        "earnings", "results beat", "profit warning", "guidance", "merger",
        "acquisition", "ipo", "layoffs", "resultats trimestriels", "dividend",
    ),
}

# ---------------------------------------------------------------------------
# Niveaux d'impact
# ---------------------------------------------------------------------------
# CRITICAL : evenement qui deplace immediatement plusieurs marches.
# Chaque terme doit designer un evenement sans ambiguite. Un mot isole trop
# courant — « war », « default », « attack » — se declenche sur des sujets
# commerciaux et bloquerait le trading sans raison.
CRITICAL_KEYWORDS: tuple[str, ...] = (
    # Decisions et faits averes uniquement. « rate hike » et « rate cut » ont
    # ete retires : la presse financiere emploie ces termes en permanence pour
    # commenter des *probabilites*. Classees critiques, ces depeches
    # declenchaient le garde-fou d'actualite en continu et le systeme ne
    # tradait plus jamais. Elles restent en impact eleve.
    "fomc", "rate decision", "raises rates", "cuts rates", "hikes rates",
    "emergency meeting", "war in", "war with", "at war", "invasion",
    "financial crisis", "crise financiere", "bank run", "sovereign default",
    "debt default", "nuclear strike", "state of emergency", "ceasefire collapse",
)

HIGH_KEYWORDS: tuple[str, ...] = (
    "rate hike", "rate cut", "hausse des taux", "baisse des taux",
    "cpi", "ppi", "nfp", "non farm payrolls", "nonfarm payrolls", "gdp", "pib",
    "unemployment", "inflation", "monetary policy", "powell", "lagarde", "opec",
    "sanction", "embargo", "tariff", "central bank", "banque centrale", "fed ",
    "ecb", "interest rate", "recession", "bailout", "bankruptcy",
)

MEDIUM_KEYWORDS: tuple[str, ...] = (
    "pmi", "ism ", "retail sales", "jobless claims", "consumer confidence",
    "industrial production", "earnings", "trade balance", "housing starts",
    "crude", "brent", "wti", "natural gas", "regulation", "lawsuit", "merger",
)

# ---------------------------------------------------------------------------
# Devises
# ---------------------------------------------------------------------------

CURRENCY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "USD": (
        "federal reserve", "fed ", "fomc", "powell", "united states", "u s ",
        "dollar", "washington", "treasury", "white house", "nfp", "etats unis",
    ),
    "EUR": (
        "ecb", "bce", "european central bank", "eurozone", "euro area", "lagarde",
        "brussels", "germany", "france", "italy", "spain", "euro", "allemagne",
    ),
    "GBP": ("bank of england", "boe ", "united kingdom", "britain", "sterling", "pound", "bailey"),
    "JPY": ("bank of japan", "boj ", "japan", "yen", "tokyo", "ueda"),
    "CHF": ("swiss national bank", "snb", "switzerland", "franc suisse"),
    "AUD": ("reserve bank of australia", "rba", "australia", "aussie dollar"),
    "NZD": ("reserve bank of new zealand", "rbnz", "new zealand"),
    "CAD": ("bank of canada", "canada", "loonie"),
    "CNY": ("china", "pboc", "beijing", "yuan", "renminbi", "chine"),
    "XAU": ("gold", "bullion", "or physique", "metal precieux"),
    "XAG": ("silver", "argent metal"),
}

# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------
# Correspondances explicites vers les symboles canoniques usuels. Un symbole
# n'est retenu que s'il figure dans la watchlist reelle de l'utilisateur.

ASSET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "XAUUSD": ("gold", "bullion", "or physique", "metal refuge"),
    "XAGUSD": ("silver", "argent metal"),
    "USOIL": ("crude", "wti", "oil price", "petrole", "opec", "opep", "barrel"),
    "UKOIL": ("brent", "north sea oil"),
    "NGAS": ("natural gas", "gaz naturel", "lng"),
    "US30": ("dow jones", "dow industrials"),
    "US500": ("s p 500", "sp500", "s and p 500"),
    "US100": ("nasdaq", "nasdaq 100", "tech stocks"),
    "GER40": ("dax", "frankfurt exchange"),
    "UK100": ("ftse", "ftse 100"),
    "JP225": ("nikkei", "nikkei 225"),
    "BTCUSD": ("bitcoin", "btc ", "crypto"),
    "ETHUSD": ("ethereum", "eth "),
}

# Devises qui portent un instrument non paire (indices, matieres premieres).
ASSET_CURRENCIES: dict[str, tuple[str, ...]] = {
    "XAUUSD": ("XAU", "USD"),
    "XAGUSD": ("XAG", "USD"),
    "USOIL": ("USD",),
    "UKOIL": ("USD", "GBP"),
    "NGAS": ("USD",),
    "US30": ("USD",),
    "US500": ("USD",),
    "US100": ("USD",),
    "GER40": ("EUR",),
    "UK100": ("GBP",),
    "JP225": ("JPY",),
    "BTCUSD": ("USD",),
    "ETHUSD": ("USD",),
}

KNOWN_CURRENCIES = frozenset(
    {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "CNY", "XAU", "XAG"}
)

# ---------------------------------------------------------------------------
# Pays
# ---------------------------------------------------------------------------

COUNTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "US": ("united states", "u s ", "washington", "white house", "america", "etats unis"),
    "EU": ("european union", "eurozone", "euro area", "brussels", "union europeenne"),
    "DE": ("germany", "berlin", "allemagne", "bundesbank"),
    "FR": ("france", "paris"),
    "GB": ("united kingdom", "britain", "london", "royaume uni"),
    "JP": ("japan", "tokyo", "japon"),
    "CN": ("china", "beijing", "chine"),
    "RU": ("russia", "moscow", "russie"),
    "UA": ("ukraine", "kyiv", "kiev"),
    "CH": ("switzerland", "suisse", "zurich"),
    "CA": ("canada", "ottawa"),
    "AU": ("australia", "sydney", "australie"),
}

# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

BULLISH_WORDS: tuple[str, ...] = (
    "beats", "beat expectations", "surge", "rally", "rebound", "record high",
    "stronger than expected", "growth accelerates", "upgrade", "optimism",
    "agreement reached", "ceasefire", "recovery", "boost", "gains", "eases",
)

BEARISH_WORDS: tuple[str, ...] = (
    "misses", "misses expectations", "plunge", "slump", "crash", "record low",
    "weaker than expected", "slowdown", "downgrade", "fears", "warning",
    "escalation", "attack", "sanction", "default", "layoffs", "contraction",
    "recession", "falls", "tumbles", "crisis",
)


def find_keywords(haystack: str, needles: tuple[str, ...]) -> list[str]:
    """Mots du vocabulaire reellement presents dans le texte normalise.

    La comparaison se fait sur des mots entiers : le texte et le mot cherche
    sont encadres d'espaces. « us » ne se declenche donc pas dans « thus », et
    « fed » ne se declenche pas dans « federal ».
    """
    padded = f" {haystack.strip()} "
    return [needle.strip() for needle in needles if f" {needle.strip()} " in padded]


# Sigles ecrits en majuscules dans les titres : « US CPI », « UK GDP »,
# « EU sanctions ». Ils sont cherches dans le texte d'origine, avant mise en
# minuscules, car « us » en minuscule est un mot anglais ordinaire.
_REGION_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bU\.?S\.?A?\.?\b"), "US", "USD"),
    (re.compile(r"\bUK\b"), "GB", "GBP"),
    (re.compile(r"\bEU\b"), "EU", "EUR"),
    (re.compile(r"\bJP\b"), "JP", "JPY"),
)


def explicit_regions(text: str | None) -> tuple[set[str], set[str]]:
    """Pays et devises deduits des sigles majuscules du texte d'origine."""
    if not text:
        return set(), set()
    countries: set[str] = set()
    currencies: set[str] = set()
    for pattern, country, currency in _REGION_PATTERNS:
        if pattern.search(text):
            countries.add(country)
            currencies.add(currency)
    return countries, currencies


def currencies_for_symbol(symbol: str) -> set[str]:
    """Devises portees par un symbole canonique.

    Une paire de six lettres est decoupee en deux devises connues. Les indices
    et matieres premieres passent par la table explicite. Un symbole inconnu
    ne produit aucune devise : on ne devine pas.
    """
    upper = symbol.strip().upper()
    if upper in ASSET_CURRENCIES:
        return set(ASSET_CURRENCIES[upper])
    if len(upper) == 6:
        base, quote = upper[:3], upper[3:]
        found = {code for code in (base, quote) if code in KNOWN_CURRENCIES}
        if found:
            return found
    return set()


__all__ = [
    "ASSET_CURRENCIES",
    "ASSET_KEYWORDS",
    "BEARISH_WORDS",
    "BULLISH_WORDS",
    "CATEGORY_KEYWORDS",
    "COUNTRY_KEYWORDS",
    "CRITICAL_KEYWORDS",
    "CURRENCY_KEYWORDS",
    "HIGH_KEYWORDS",
    "KNOWN_CURRENCIES",
    "MEDIUM_KEYWORDS",
    "currencies_for_symbol",
    "explicit_regions",
    "find_keywords",
    "normalize",
]
