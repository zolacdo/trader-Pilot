"""Lecture IA d'un contexte deja analyse (CDC3 sections 20 a 22, 75 et 76).

Trois regles, non negociables, sont appliquees ici plutot que promises :

1. **L'IA ne voit jamais un contexte vide.** Elle recoit des mesures deja
   calculees, en clair, et on lui demande de les commenter — pas de les
   deviner.
2. **L'IA n'invente aucun prix.** Sa reponse ne contient aucun champ de
   niveau, et rien de ce qu'elle renvoie n'est reinjecte dans Entry, SL ou TP
   (CDC3 section 22). Elle ne peut qu'ajouter un commentaire et des risques.
3. **L'IA ne remplace aucune regle.** Le Risk Manager passe apres elle et peut
   refuser malgre un avis enthousiaste.

On ne demande aucune chaine de pensee (CDC3 section 76) : seulement un resume
des facteurs, les risques, et un resultat structure valide par Pydantic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.config.logging_config import get_logger
from app.models.enums import Direction
from app.models.intelligence import AITaskKind
from app.watcher.analysis.context import MarketContext
from app.watcher.config import WatcherConfig
from app.watcher.levels import TradeLevels
from app.watcher.scoring import ScoreCard

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "Tu es un analyste de marche. On te fournit des mesures deja calculees sur "
    "des donnees reelles. Tu ne dois JAMAIS proposer de prix d'entree, de stop "
    "ou d'objectif : ils sont deja fixes et ne t'appartiennent pas. Tu evalues "
    "la coherence de la lecture, tu signales les risques, et tu reponds "
    "uniquement par un objet JSON valide, sans texte autour, sans raisonnement "
    "detaille."
)

# Taille du cache de lectures IA (CDC3 section 74). Un contexte identique ne
# doit pas etre paye deux fois.
CACHE_SIZE = 128

# Budget de sortie genereux, et ce n'est pas du gaspillage : les modeles
# recents (gemini-flash notamment) consomment des jetons de raisonnement AVANT
# d'ecrire leur reponse. Mesure sur ce projet : a 600 jetons, la reponse
# s'arretait au milieu du JSON — donc inexploitable, donc rejetee par le
# routeur, donc aucune lecture IA ne sortait jamais. A 2000, le JSON revient
# complet. La reponse utile fait environ 730 caracteres : le reste du budget
# n'est facture que s'il est consomme.
MAX_TOKENS = 2000


class AIOpinion(BaseModel):
    """Schema impose a la reponse du modele (CDC3 section 75)."""

    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"] = "NEUTRAL"
    confidence: int = Field(default=0, ge=0, le=100)
    fundamental_impact: Literal["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"] = "UNKNOWN"
    sentiment: int = Field(default=0, ge=-100, le=100)
    risks: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    recommendation: Literal["BUY", "SELL", "WAIT", "NO_TRADE"] = "WAIT"

    def agrees_with(self, direction: Direction) -> bool:
        wanted = "BUY" if direction is Direction.BUY else "SELL"
        return self.recommendation == wanted


@dataclass(slots=True)
class AIReading:
    """Ce que l'IA a repondu, et d'ou cela vient."""

    available: bool = False
    opinion: AIOpinion | None = None
    provider: str | None = None
    model: str | None = None
    cached: bool = False
    reason: str | None = None

    @property
    def comment(self) -> str | None:
        if self.opinion is None:
            return None
        return self.opinion.reasoning_summary.strip() or None

    @property
    def risks(self) -> list[str]:
        return list(self.opinion.risks) if self.opinion is not None else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "provider": self.provider,
            "model": self.model,
            "cached": self.cached,
            "reason": self.reason,
            "opinion": self.opinion.model_dump() if self.opinion else None,
        }


_cache: dict[str, AIReading] = {}


def _fingerprint(payload: dict[str, Any]) -> str:
    """Empreinte stable du contexte, pour ne pas payer deux fois la meme lecture."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_prompt(
    context: MarketContext, direction: Direction, levels: TradeLevels, card: ScoreCard
) -> tuple[str, dict[str, Any]]:
    """Prompt et empreinte associee. Les niveaux sont donnes, jamais demandes."""
    payload: dict[str, Any] = {
        "instrument": context.symbol,
        "sens_envisage": direction.value,
        "prix_courant": context.price,
        "unite_de_travail": context.primary_timeframe.value if context.primary_timeframe else None,
        "biais_multi_timeframe": context.bias.value,
        "etats_par_timeframe": context.view.states() if context.view else {},
        "structure": context.primary.structure.label if context.primary else None,
        "volatilite": context.volatility.detail,
        "volume": context.volume.detail,
        "price_action": context.price_action.detail,
        "liquidite": context.liquidity.detail,
        "sentiment_actualites": context.sentiment.detail,
        "fondamental": context.fundamental.detail,
        "titres_recents": context.sentiment.headlines,
        "annonce_imminente": context.news_guard.reason,
        "niveaux_deja_calcules": {
            "entree": levels.entry,
            "stop": levels.stop_loss,
            "objectifs": levels.targets,
            "risk_reward": levels.risk_rewards,
        },
        "score_deterministe": round(card.score, 1),
        "criteres": {
            item.key: {"points": round(item.points, 2), "sur": item.weight, "detail": item.detail}
            for item in card.criteria
        },
        "donnees_manquantes": card.missing,
    }

    prompt = (
        "Voici l'analyse deterministe d'un instrument financier. "
        "Les niveaux sont deja fixes : ne les modifie pas, ne les commente que "
        "s'ils sont incoherents avec le contexte.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n\n"
        "Reponds uniquement par cet objet JSON :\n"
        "{\n"
        '  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",\n'
        '  "confidence": 0-100,\n'
        '  "fundamental_impact": "BULLISH" | "BEARISH" | "NEUTRAL" | "UNKNOWN",\n'
        '  "sentiment": -100 a 100,\n'
        '  "risks": ["risque concret", "..."],\n'
        '  "reasoning_summary": "trois phrases maximum, en francais",\n'
        '  "recommendation": "BUY" | "SELL" | "WAIT" | "NO_TRADE"\n'
        "}\n"
        "Si une information manque, ecris UNKNOWN plutot que de la supposer."
    )
    return prompt, payload


async def review(
    context: MarketContext,
    direction: Direction,
    levels: TradeLevels,
    card: ScoreCard,
    config: WatcherConfig,
) -> AIReading:
    """Demande une lecture IA, si et seulement si elle en vaut la peine.

    Sous le seuil ``ai_min_score``, l'analyse deterministe a deja tranche :
    payer un appel n'apporterait rien (CDC3 section 73).
    """
    if not config.ai_enabled:
        return AIReading(reason="Lecture IA desactivee dans les reglages.")
    if card.score < config.ai_min_score:
        return AIReading(
            reason=(
                f"Score {round(card.score, 1)} sous le seuil d'appel IA "
                f"({config.ai_min_score}) : aucun appel effectue."
            )
        )

    prompt, payload = build_prompt(context, direction, levels, card)
    key = _fingerprint(payload)
    cached = _cache.get(key)
    if cached is not None:
        return AIReading(
            available=cached.available,
            opinion=cached.opinion,
            provider=cached.provider,
            model=cached.model,
            cached=True,
            reason=cached.reason,
        )

    from app.services.ai.service import ai_service

    try:
        routed = await ai_service.complete_json(
            prompt,
            system=SYSTEM_PROMPT,
            task=AITaskKind.MARKET_ANALYSIS,
            max_tokens=MAX_TOKENS,
        )
    except Exception as exc:
        # L'indisponibilite de l'IA ne doit jamais empecher un signal
        # deterministe de partir (CDC3 section 55).
        logger.info("Lecture IA impossible sur %s : %s", context.symbol, exc)
        return AIReading(reason=f"Moteur IA indisponible : {exc}")

    if routed is None:
        return AIReading(reason="Aucun moteur IA disponible pour cette analyse.")

    response = routed.response
    if not response.valid_json or not isinstance(response.payload, dict):
        logger.info("Reponse IA non exploitable sur %s : JSON invalide", context.symbol)
        return AIReading(
            provider=routed.provider.value,
            model=response.model,
            reason="Reponse IA invalide : JSON attendu, non recu.",
        )

    try:
        opinion = AIOpinion.model_validate(response.payload)
    except ValidationError as exc:
        logger.info("Reponse IA hors schema sur %s : %s", context.symbol, exc.error_count())
        return AIReading(
            provider=routed.provider.value,
            model=response.model,
            reason="Reponse IA hors schema attendu.",
        )

    reading = AIReading(
        available=True,
        opinion=opinion,
        provider=routed.provider.value,
        model=response.model,
    )
    _remember(key, reading)
    return reading


def _remember(key: str, reading: AIReading) -> None:
    """Memorise la lecture, en bornant la taille du cache."""
    if len(_cache) >= CACHE_SIZE:
        # Le plus ancien sort : les dictionnaires Python conservent l'ordre
        # d'insertion, ce qui suffit largement ici.
        _cache.pop(next(iter(_cache)))
    _cache[key] = reading


def clear_cache() -> None:
    """Vide le cache des lectures IA (tests, changement de modele)."""
    _cache.clear()


__all__ = ["AIOpinion", "AIReading", "build_prompt", "clear_cache", "review"]
