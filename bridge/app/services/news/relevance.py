"""NewsRelevanceEngine : qualification d'une actualite (CDC2 sections 29 et 30).

Pipeline impose :

    news brute -> prefiltre deterministe -> IA (locale d'abord) -> resultat

Le prefiltre traite seul la majorite des depeches. L'IA n'est sollicitee que
dans deux cas : le prefiltre n'a rien reconnu (ambigu), ou l'evenement est
juge tres important et merite une seconde lecture.

Si aucune intelligence n'est disponible, ``ai_service.complete_json`` retourne
``None`` : le resultat deterministe est conserve tel quel et la raison le dit.
Jamais d'impact invente, jamais de chiffre fabrique.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.config.logging_config import get_logger
from app.models.intelligence import AIProviderKind, AITaskKind, NewsImpact, NewsSentiment
from app.services.ai.base import MIN_JSON_MAX_TOKENS
from app.services.news.providers import RawNewsItem
from app.services.news.taxonomy import (
    ASSET_KEYWORDS,
    BEARISH_WORDS,
    BULLISH_WORDS,
    CATEGORY_KEYWORDS,
    COUNTRY_KEYWORDS,
    CRITICAL_KEYWORDS,
    CURRENCY_KEYWORDS,
    HIGH_KEYWORDS,
    MEDIUM_KEYWORDS,
    currencies_for_symbol,
    explicit_regions,
    find_keywords,
    normalize,
)

logger = get_logger(__name__)

IMPACT_ORDER: tuple[NewsImpact, ...] = (
    NewsImpact.LOW,
    NewsImpact.MEDIUM,
    NewsImpact.HIGH,
    NewsImpact.CRITICAL,
)
_IMPACT_RANK = {impact: index for index, impact in enumerate(IMPACT_ORDER)}

SYSTEM_PROMPT = (
    "Tu classes des depeches financieres. Reponds uniquement par un objet JSON. "
    "N'invente aucun chiffre et aucune source. Si tu ne sais pas, mets null."
)


@dataclass(slots=True)
class RelevanceResult:
    """Qualification complete d'une actualite (champs du CDC2 section 29)."""

    category: str | None = None
    countries: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    affected_assets: list[str] = field(default_factory=list)
    affected_currencies: list[str] = field(default_factory=list)
    impact: NewsImpact = NewsImpact.LOW
    sentiment: NewsSentiment = NewsSentiment.NEUTRAL
    confidence: float = 0.0
    reason: str = ""
    ai_provider: AIProviderKind | None = None
    ai_model: str | None = None
    ai_consulted: bool = False
    escalation_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "countries": list(self.countries),
            "entities": list(self.entities),
            "affectedAssets": list(self.affected_assets),
            "affectedCurrencies": list(self.affected_currencies),
            "impactLevel": self.impact.value,
            "sentiment": self.sentiment.value,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def rank(impact: NewsImpact) -> int:
    return _IMPACT_RANK[impact]


class NewsRelevanceEngine:
    """Qualifie une actualite : deterministe d'abord, IA ensuite si utile."""

    def __init__(self, ai: Any | None = None) -> None:
        # Injectable pour les tests ; par defaut le service hybride du Bridge.
        self._ai = ai

    def _resolve_ai(self) -> Any | None:
        if self._ai is not None:
            return self._ai
        from app.services.ai.service import ai_service

        return ai_service

    # ------------------------------------------------------------------
    # Etape 1 : prefiltre deterministe
    # ------------------------------------------------------------------
    def prefilter(self, item: RawNewsItem, watchlist: list[str] | None = None) -> RelevanceResult:
        """Lecture purement lexicale : mots-cles, devises, instruments suivis."""
        symbols = [s.strip().upper() for s in (watchlist or []) if s and s.strip()]
        raw_text = f"{item.title} {item.summary or ''}"
        haystack = normalize(raw_text) + " "
        raw_countries, raw_currencies = explicit_regions(raw_text)

        category = self._detect_category(haystack) or item.category
        countries = self._detect_countries(haystack, item, raw_countries)
        currencies = self._detect_currencies(haystack, item, raw_currencies)
        assets, asset_currencies = self._detect_assets(haystack, symbols, currencies)
        currencies = sorted(set(currencies) | asset_currencies)
        impact, impact_reason = self._detect_impact(haystack, item, bool(assets))
        sentiment = self._detect_sentiment(haystack)
        entities = self._detect_entities(haystack)

        reasons = [impact_reason]
        if assets:
            reasons.append(f"instruments suivis concernés : {', '.join(assets)}")
        elif symbols:
            reasons.append("aucun instrument de la watchlist n'est cité")
        if currencies:
            reasons.append(f"devises : {', '.join(currencies)}")

        confidence = self._prefilter_confidence(impact, assets, currencies, category)
        return RelevanceResult(
            category=category,
            countries=countries,
            entities=entities,
            affected_assets=assets,
            affected_currencies=currencies,
            impact=impact,
            sentiment=sentiment,
            confidence=confidence,
            reason="Préfiltre déterministe : " + " ; ".join(r for r in reasons if r),
        )

    @staticmethod
    def _detect_category(haystack: str) -> str | None:
        best: tuple[str, int] | None = None
        for name, keywords in CATEGORY_KEYWORDS.items():
            hits = len(find_keywords(haystack, keywords))
            if hits and (best is None or hits > best[1]):
                best = (name, hits)
        return best[0] if best else None

    @staticmethod
    def _detect_countries(haystack: str, item: RawNewsItem, extra: set[str]) -> list[str]:
        found = {code for code, words in COUNTRY_KEYWORDS.items() if find_keywords(haystack, words)}
        found.update(code for code in item.countries if code and code != "WORLD")
        found.update(extra)
        return sorted(found)

    @staticmethod
    def _detect_currencies(haystack: str, item: RawNewsItem, extra: set[str]) -> list[str]:
        found = {code for code, words in CURRENCY_KEYWORDS.items() if find_keywords(haystack, words)}
        found.update(code for code in item.currencies if code)
        found.update(extra)
        return sorted(found)

    @staticmethod
    def _detect_assets(
        haystack: str, watchlist: list[str], currencies: list[str]
    ) -> tuple[list[str], set[str]]:
        """Instruments concernes, limites a ceux que l'utilisateur suit.

        Deux liens possibles : le nom de l'instrument apparait dans le texte,
        ou l'une de ses devises est concernee. Sans watchlist, on se contente
        des correspondances lexicales explicites.
        """
        named = {
            symbol for symbol, words in ASSET_KEYWORDS.items() if find_keywords(haystack, words)
        }
        if not watchlist:
            matched = sorted(named)
            return matched, {c for symbol in matched for c in currencies_for_symbol(symbol)}

        currency_set = set(currencies)
        matched: set[str] = set()
        used_currencies: set[str] = set()
        for symbol in watchlist:
            symbol_currencies = currencies_for_symbol(symbol)
            if symbol in named:
                matched.add(symbol)
                used_currencies |= symbol_currencies
            elif symbol_currencies & currency_set:
                matched.add(symbol)
                used_currencies |= symbol_currencies & currency_set
        return sorted(matched), used_currencies

    @staticmethod
    def _detect_impact(haystack: str, item: RawNewsItem, has_assets: bool) -> tuple[NewsImpact, str]:
        if find_keywords(haystack, CRITICAL_KEYWORDS):
            hits = find_keywords(haystack, CRITICAL_KEYWORDS)
            return NewsImpact.CRITICAL, f"mots-clés critiques repérés ({', '.join(hits[:3])})"
        if find_keywords(haystack, HIGH_KEYWORDS):
            hits = find_keywords(haystack, HIGH_KEYWORDS)
            return NewsImpact.HIGH, f"mots-clés à fort impact repérés ({', '.join(hits[:3])})"
        if find_keywords(haystack, MEDIUM_KEYWORDS):
            hits = find_keywords(haystack, MEDIUM_KEYWORDS)
            return NewsImpact.MEDIUM, f"mots-clés d'impact modéré repérés ({', '.join(hits[:3])})"
        if item.official and has_assets:
            return NewsImpact.MEDIUM, "source institutionnelle citant un instrument suivi"
        return NewsImpact.LOW, "aucun mot-clé d'impact identifié : impact non déterminable, laissé à LOW"

    @staticmethod
    def _detect_sentiment(haystack: str) -> NewsSentiment:
        bullish = len(find_keywords(haystack, BULLISH_WORDS))
        bearish = len(find_keywords(haystack, BEARISH_WORDS))
        if bullish and bearish:
            return NewsSentiment.MIXED
        if bullish:
            return NewsSentiment.BULLISH
        if bearish:
            return NewsSentiment.BEARISH
        return NewsSentiment.NEUTRAL

    @staticmethod
    def _detect_entities(haystack: str) -> list[str]:
        """Institutions et responsables nommement cites."""
        known = {
            "Federal Reserve": ("federal reserve", "fomc"),
            "BCE": ("ecb", "european central bank", "bce"),
            "Bank of England": ("bank of england",),
            "Banque du Japon": ("bank of japan",),
            "OPEP": ("opec", "opep"),
            "FMI": ("imf", "international monetary fund"),
            "SEC": ("sec charges", "securities and exchange commission"),
            "Jerome Powell": ("powell",),
            "Christine Lagarde": ("lagarde",),
        }
        return sorted(name for name, words in known.items() if find_keywords(haystack, words))

    @staticmethod
    def _prefilter_confidence(
        impact: NewsImpact, assets: list[str], currencies: list[str], category: str | None
    ) -> float:
        score = 0.3
        if category:
            score += 0.15
        if currencies:
            score += 0.15
        if assets:
            score += 0.15
        if impact is not NewsImpact.LOW:
            score += 0.1
        return round(min(score, 0.85), 3)

    # ------------------------------------------------------------------
    # Etape 2 : faut-il consulter l'IA ?
    # ------------------------------------------------------------------
    @staticmethod
    def escalation_reason(result: RelevanceResult) -> str | None:
        """Motif de l'appel a l'IA, ou ``None`` si le deterministe suffit.

        C'est ici que se joue le cout : une depeche ordinaire deja reconnue
        par le prefiltre ne declenche aucun appel (CDC2 section 30).

        Mesure du 13/09/2026 : 355 des 363 appels IA de la journee venaient
        d'ici, soit 98 % du budget. La cause etait une regle a l'envers --
        une depeche SANS aucun rattachement marche escaladait vers l'IA,
        alors qu'une depeche sans rattachement est justement celle qui ne
        concerne pas le portefeuille. Sur 220 depeches, 89 seulement avaient
        un lien : les ~130 autres consommaient le quota pour rien.

        La regle est desormais celle-ci : on paie une seconde lecture quand
        la depeche PEUT compter et qu'on doute, jamais quand le prefiltre a
        deja etabli qu'elle ne touche aucun marche suivi.
        """
        if rank(result.impact) >= rank(NewsImpact.HIGH):
            return "impact élevé : seconde lecture demandée"

        rattachee = bool(result.affected_currencies or result.affected_assets)
        if not rattachee:
            # Aucun marche concerne : le deterministe suffit, et l'IA ne
            # trouverait de toute facon rien a rattacher.
            return None

        if result.category is None:
            return "marché concerné mais catégorie non reconnue"
        return None

    # ------------------------------------------------------------------
    # Etape 3 : evaluation complete
    # ------------------------------------------------------------------
    async def evaluate(
        self, item: RawNewsItem, watchlist: list[str] | None = None
    ) -> RelevanceResult:
        """Qualification finale d'une actualite."""
        result = self.prefilter(item, watchlist)
        reason = self.escalation_reason(result)
        result.escalation_reason = reason
        if reason is None:
            return result

        service = self._resolve_ai()
        if service is None:
            result.reason += " ; aucune IA configurée, résultat déterministe conservé"
            return result

        payload = await self._ask_ai(service, item, result, watchlist or [])
        if payload is None:
            result.reason += " ; IA indisponible, résultat déterministe conservé"
            return result
        return self._merge_ai(result, payload, watchlist or [])

    async def _ask_ai(
        self, service: Any, item: RawNewsItem, result: RelevanceResult, watchlist: list[str]
    ) -> dict[str, Any] | None:
        prompt = self._build_prompt(item, result, watchlist)
        try:
            routed = await service.complete_json(
                prompt,
                system=SYSTEM_PROMPT,
                task=AITaskKind.NEWS_CLASSIFY,
                max_tokens=MIN_JSON_MAX_TOKENS,
            )
        except Exception as exc:
            logger.info("Classification IA impossible : %s", exc)
            return None
        if routed is None:
            return None
        result.ai_consulted = True
        result.ai_provider = routed.provider
        result.ai_model = routed.response.model
        payload = routed.response.payload
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _build_prompt(item: RawNewsItem, result: RelevanceResult, watchlist: list[str]) -> str:
        context = {
            "titre": item.title,
            "resume": (item.summary or "")[:600],
            "source": item.source_name,
            "sourceOfficielle": item.official,
            "prefiltre": result.to_dict(),
            "watchlist": watchlist[:40],
        }
        return (
            "Classe cette depeche financiere.\n"
            f"Donnees : {json.dumps(context, ensure_ascii=False)}\n\n"
            "Reponds avec cet objet JSON exactement :\n"
            '{"category": str|null, "impact": "LOW"|"MEDIUM"|"HIGH"|"CRITICAL"|null, '
            '"sentiment": "BULLISH"|"BEARISH"|"NEUTRAL"|"MIXED"|null, '
            '"confidence": nombre entre 0 et 1, '
            '"affectedCurrencies": liste de codes ISO, '
            '"affectedAssets": liste de symboles pris dans la watchlist fournie, '
            '"entities": liste de noms cites, "reason": phrase courte en francais}\n'
            "N'ajoute aucun champ. N'invente ni chiffre ni symbole absent de la watchlist."
        )

    def _merge_ai(
        self, result: RelevanceResult, payload: dict[str, Any], watchlist: list[str]
    ) -> RelevanceResult:
        """Fusionne la lecture IA avec le deterministe, sans jamais lui ceder.

        L'IA peut preciser une categorie, un sentiment, ajouter des devises et
        ajuster l'impact d'un cran. Elle ne peut pas inventer un symbole absent
        de la watchlist, ni faire passer une depeche de LOW a CRITICAL.
        """
        allowed = {s.strip().upper() for s in watchlist}

        impact = _parse_enum(payload.get("impact"), NewsImpact)
        if impact is not None:
            delta = rank(impact) - rank(result.impact)
            if delta > 1:
                impact = IMPACT_ORDER[rank(result.impact) + 1]
            elif delta < -1:
                impact = IMPACT_ORDER[rank(result.impact) - 1]
            result.impact = impact

        sentiment = _parse_enum(payload.get("sentiment"), NewsSentiment)
        if sentiment is not None:
            result.sentiment = sentiment

        category = payload.get("category")
        if isinstance(category, str) and category.strip():
            result.category = category.strip()[:64]

        currencies = _string_list(payload.get("affectedCurrencies"))
        if currencies:
            result.affected_currencies = sorted(set(result.affected_currencies) | set(currencies))

        assets = [s for s in _string_list(payload.get("affectedAssets")) if not allowed or s in allowed]
        if assets:
            result.affected_assets = sorted(set(result.affected_assets) | set(assets))

        entities = _string_list(payload.get("entities"), upper=False)
        if entities:
            result.entities = sorted(set(result.entities) | set(entities))

        confidence = payload.get("confidence")
        if isinstance(confidence, int | float) and 0.0 <= float(confidence) <= 1.0:
            # Moyenne : ni le deterministe ni l'IA ne decide seul.
            result.confidence = round((result.confidence + float(confidence)) / 2, 3)

        reason = payload.get("reason")
        provider = result.ai_provider.value if result.ai_provider else "IA"
        if isinstance(reason, str) and reason.strip():
            result.reason = f"{result.reason} ; {provider} : {reason.strip()[:200]}"
        else:
            result.reason = f"{result.reason} ; {provider} consultée, sans motif exploitable"
        return result


def _parse_enum(value: Any, enum_cls: Any) -> Any | None:
    if not isinstance(value, str):
        return None
    try:
        return enum_cls(value.strip().upper())
    except ValueError:
        return None


def _string_list(value: Any, *, upper: bool = True) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        cleaned = entry.strip()
        if cleaned:
            out.append(cleaned.upper()[:32] if upper else cleaned[:64])
    return out


__all__ = ["IMPACT_ORDER", "NewsRelevanceEngine", "RelevanceResult", "rank"]
