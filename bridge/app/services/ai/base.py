"""Contrat commun aux moteurs d'intelligence artificielle (CDC2 section 4).

Une seule implementation existe : OpenRouter. Le contrat est conserve car ce
qui varie desormais est le modele, pas le fournisseur : ``complete`` accepte
un identifiant de modele, ce qui permet de confronter deux modeles distincts
sur une meme question.

Regle absolue : une sortie de modele n'est jamais une verite. Elle est
structuree, validee, puis confrontee aux donnees deterministes avant de
pouvoir influencer une decision (CDC2 section 15).
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models.intelligence import AIProviderKind, AITaskKind

# Blocs ```json ... ``` que les modeles ajoutent spontanement.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


# Plancher de jetons pour toute sortie JSON structuree.
#
# Les modeles recents raisonnent avant d'ecrire, et le budget max_tokens couvre
# les deux depenses. Mesure du 13/09/2026 sur nvidia/nemotron-3-ultra via
# OpenRouter, avec le meme prompt de classification :
#
#      400 jetons -> aucune reponse du tout, la liste des choix revient vide
#     2000 jetons -> JSON complet, 96 caracteres
#
# Un budget calibre sur la taille de la reponse attendue est donc toujours trop
# court. L'echec est silencieux : le routeur ecarte le moteur et l'appelant ne
# voit que « aucune IA disponible », ce qui fait chercher une panne de cle ou
# de quota. Le plancher empeche un nouvel appel de reintroduire le probleme.
MIN_JSON_MAX_TOKENS = 2000


def json_token_budget(max_tokens: int, json_mode: bool) -> int:
    """Budget effectif : jamais sous le plancher quand du JSON est attendu."""
    if not json_mode:
        return max_tokens
    return max(max_tokens, MIN_JSON_MAX_TOKENS)


class AIProviderError(Exception):
    """Le moteur n'a pas pu repondre : indisponible, delai depasse, refus."""


class AIProviderUnavailable(AIProviderError):
    """Le moteur n'est pas configure ou ne repond pas du tout."""


@dataclass(slots=True)
class AICapabilities:
    """Ce que le moteur sait reellement faire, tel que declare ou teste."""

    text: bool = True
    json_mode: bool = False
    tools: bool = False
    vision: bool = False
    context_size: int = 8192

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "json": self.json_mode,
            "tools": self.tools,
            "vision": self.vision,
            "contextSize": self.context_size,
        }


@dataclass(slots=True)
class AIResponse:
    """Reponse normalisee d'un moteur."""

    provider: AIProviderKind
    model: str
    text: str
    latency_ms: int
    payload: dict[str, Any] | None = None
    valid_json: bool = False
    truncated: bool = False
    raw_usage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "model": self.model,
            "latencyMs": self.latency_ms,
            "validJson": self.valid_json,
            "payload": self.payload,
            "text": self.text[:2000],
        }


@dataclass(slots=True)
class AIProviderStatus:
    """Etat d'un moteur, affiche dans le diagnostic (CDC2 section 96)."""

    kind: AIProviderKind
    configured: bool = False
    available: bool = False
    model: str | None = None
    vision_model: str | None = None
    capabilities: AICapabilities = field(default_factory=AICapabilities)
    latency_ms: int | None = None
    error: str | None = None
    detail: str | None = None

    @property
    def health(self) -> str:
        if not self.configured:
            return "OFFLINE"
        if self.available:
            return "ONLINE"
        return "DEGRADED" if self.model else "OFFLINE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.kind.value,
            "health": self.health,
            "configured": self.configured,
            "available": self.available,
            "model": self.model,
            "visionModel": self.vision_model,
            "capabilities": self.capabilities.to_dict(),
            "latencyMs": self.latency_ms,
            "error": self.error,
            "detail": self.detail,
        }


def extract_json(text: str) -> dict[str, Any] | None:
    """Recupere l'objet JSON d'une reponse de modele.

    Les modeles entourent souvent leur JSON de texte ou de balises Markdown.
    On tente, dans l'ordre : le texte brut, le contenu d'un bloc de code, puis
    la premiere accolade equilibree. Aucun devinement : si rien n'est valide,
    on retourne None et l'appelant traite l'echec.
    """
    if not text:
        return None

    candidates: list[str] = [text.strip()]

    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())

    start = text.find("{")
    if start != -1:
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class AIProvider(ABC):
    """Moteur d'intelligence artificielle interchangeable."""

    kind: AIProviderKind

    @abstractmethod
    async def status(self) -> AIProviderStatus:
        """Etat courant, sans jamais lever."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        task: AITaskKind = AITaskKind.MARKET_ANALYSIS,
        json_mode: bool = False,
        max_tokens: int = 800,
        temperature: float = 0.1,
        timeout: float | None = None,
        image_base64: str | None = None,
        model: str | None = None,
    ) -> AIResponse:
        """Interroge le moteur. Leve ``AIProviderError`` en cas d'echec.

        ``model`` force un modele precis. Sans lui, le moteur retient celui
        que la selection automatique a choisi.
        """

    async def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        task: AITaskKind = AITaskKind.MARKET_ANALYSIS,
        max_tokens: int = 800,
        timeout: float | None = None,
        model: str | None = None,
    ) -> AIResponse:
        """Variante attendant un objet JSON.

        Le drapeau ``valid_json`` dit si la sortie etait exploitable : c'est
        cette mesure qui alimente la fiabilite du moteur (CDC2 section 14).
        """
        response = await self.complete(
            prompt,
            system=system,
            task=task,
            json_mode=True,
            max_tokens=max_tokens,
            timeout=timeout,
            model=model,
        )
        payload = extract_json(response.text)
        response.payload = payload
        response.valid_json = payload is not None
        return response

    async def list_models(self) -> list[dict[str, Any]]:
        """Modeles disponibles. Liste vide lorsque le moteur ne l'expose pas."""
        return []
