"""Normalisation des instruments : alias Telegram -> symbole canonique.

La correspondance vers le symbole reellement disponible chez le broker
(ex: ``XAUUSDm`` chez Exness) est resolue separement par le SymbolResolver,
qui interroge la liste reelle des symboles MT5 (CDC section 54).
"""

from __future__ import annotations

import re
from itertools import pairwise

# Devises majeures utilisees pour reconnaitre une paire ecrite librement.
CURRENCIES = {
    "EUR", "USD", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
    "SEK", "NOK", "DKK", "PLN", "TRY", "ZAR", "MXN", "SGD",
    "HKD", "CNH", "CZK", "HUF", "THB", "XAU", "XAG", "XPT", "XPD",
}

METALS = {"XAU", "XAG", "XPT", "XPD"}

# Alias explicites -> symbole canonique
ALIASES: dict[str, str] = {
    # metaux
    "GOLD": "XAUUSD",
    "GOLDUSD": "XAUUSD",
    "XAU": "XAUUSD",
    "XAUUSD": "XAUUSD",
    "OR": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAG": "XAGUSD",
    "XAGUSD": "XAGUSD",
    "PLATINUM": "XPTUSD",
    "PALLADIUM": "XPDUSD",
    # indices
    "US30": "US30",
    "DOW": "US30",
    "DOWJONES": "US30",
    "DJI": "US30",
    "DJIA": "US30",
    "WALLSTREET": "US30",
    "NAS100": "NAS100",
    "NAS": "NAS100",
    "NASDAQ": "NAS100",
    "NASDAQ100": "NAS100",
    "USTEC": "NAS100",
    "NDX": "NAS100",
    "US100": "NAS100",
    "SPX500": "SPX500",
    "SP500": "SPX500",
    "SPX": "SPX500",
    "US500": "SPX500",
    "GER40": "GER40",
    "GER30": "GER40",
    "DAX": "GER40",
    "DAX40": "GER40",
    "DE40": "GER40",
    "UK100": "UK100",
    "FTSE": "UK100",
    "FTSE100": "UK100",
    "JP225": "JP225",
    "NIKKEI": "JP225",
    "FRA40": "FRA40",
    "CAC40": "FRA40",
    "AUS200": "AUS200",
    "HK50": "HK50",
    # energie
    "OIL": "XTIUSD",
    "WTI": "XTIUSD",
    "CRUDE": "XTIUSD",
    "CRUDEOIL": "XTIUSD",
    "USOIL": "XTIUSD",
    "XTIUSD": "XTIUSD",
    "BRENT": "XBRUSD",
    "UKOIL": "XBRUSD",
    "XBRUSD": "XBRUSD",
    "NATGAS": "XNGUSD",
    "GAS": "XNGUSD",
    # crypto
    "BTC": "BTCUSD",
    "BITCOIN": "BTCUSD",
    "BTCUSD": "BTCUSD",
    "BTCUSDT": "BTCUSD",
    "ETH": "ETHUSD",
    "ETHEREUM": "ETHUSD",
    "ETHUSD": "ETHUSD",
    "XRP": "XRPUSD",
    "SOL": "SOLUSD",
    "LTC": "LTCUSD",
    "DOGE": "DOGEUSD",
    # raccourcis forex frequents
    "EU": "EURUSD",
    "GU": "GBPUSD",
    "UJ": "USDJPY",
    "AU": "AUDUSD",
    "UC": "USDCAD",
    "GJ": "GBPJPY",
    "EJ": "EURJPY",
    "CABLE": "GBPUSD",
    "FIBER": "EURUSD",
}

# Suffixes broker frequents a retirer avant comparaison (Exness : m, c, z, .r)
BROKER_SUFFIX_PATTERN = re.compile(r"^([A-Z0-9]{5,10}?)(M|C|Z|E|PRO|ECN|RAW|\.R|\.A|MICRO|\.C|\.M|_I|\.P)$")

_SEPARATOR_PATTERN = re.compile(r"[\s/\\\-_.,]+")
_TOKEN_CLEAN = re.compile(r"[^A-Z0-9]")


def clean_token(token: str) -> str:
    return _TOKEN_CLEAN.sub("", token.upper())


def is_currency_pair(token: str) -> bool:
    token = clean_token(token)
    return len(token) == 6 and token[:3] in CURRENCIES and token[3:] in CURRENCIES


def canonical_symbol(raw: str | None, extra_aliases: dict[str, str] | None = None) -> str | None:
    """Retourne le symbole canonique ou None si le texte n'est pas un instrument."""
    if not raw:
        return None
    token = clean_token(raw)
    if not token:
        return None

    lookup = dict(ALIASES)
    if extra_aliases:
        lookup.update({clean_token(k): v.upper() for k, v in extra_aliases.items()})

    if token in lookup:
        return lookup[token]
    if is_currency_pair(token):
        return token
    # XAUUSD ecrit XAU/USD ou XAU USD -> deja nettoye ci-dessus
    if len(token) == 6 and token[:3] in METALS:
        return token
    # tolerance suffixe broker : XAUUSDM -> XAUUSD
    match = BROKER_SUFFIX_PATTERN.match(token)
    if match:
        base = match.group(1)
        if base in lookup:
            return lookup[base]
        if is_currency_pair(base):
            return base
    if token in {"US30", "NAS100", "SPX500", "GER40", "UK100", "JP225", "FRA40", "AUS200", "HK50"}:
        return token
    return None


def extract_symbol(text: str, extra_aliases: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    """Cherche un instrument dans un texte libre.

    Retourne ``(texte_original_trouve, symbole_canonique)`` ou ``(None, None)``.
    """
    if not text:
        return None, None
    upper = text.upper()

    # 1) formes explicites avec separateur : XAU/USD, EUR-USD, XAU USD
    for match in re.finditer(r"\b([A-Z]{3})\s*[/\\\-]\s*([A-Z]{3})\b", upper):
        candidate = match.group(1) + match.group(2)
        canonical = canonical_symbol(candidate, extra_aliases)
        if canonical:
            return match.group(0), canonical

    # 2) tokens simples (alias, paires collees, indices)
    for match in re.finditer(r"\b([A-Z]{2,12}[0-9]{0,3})\b", upper):
        token = match.group(1)
        canonical = canonical_symbol(token, extra_aliases)
        if canonical:
            return token, canonical

    # 3) alias en deux mots : "XAU USD"
    tokens = _SEPARATOR_PATTERN.split(upper)
    for first, second in pairwise(tokens):
        if len(first) == 3 and len(second) == 3:
            canonical = canonical_symbol(first + second, extra_aliases)
            if canonical:
                return f"{first} {second}", canonical
    return None, None


def all_aliases_for(canonical: str) -> list[str]:
    target = canonical.upper()
    return sorted({alias for alias, value in ALIASES.items() if value == target} | {target})


def strip_broker_suffix(symbol: str) -> str:
    token = clean_token(symbol)
    match = BROKER_SUFFIX_PATTERN.match(token)
    return match.group(1) if match else token
