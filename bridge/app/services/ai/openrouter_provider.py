"""Adaptation d'OpenRouter au contrat commun des moteurs IA.

Toute la mecanique existante est conservee (CDC2 section 8) : selection
dynamique des modeles gratuits, coupe-circuit, refus des modeles payants.
Cette classe presente ce service sous le contrat commun, en laissant
l'appelant viser un modele precis : c'est ce qui permet de confronter deux
modeles gratuits sur une meme question.
"""

from __future__ import annotations

import time
from typing import Any

from app.config.logging_config import get_logger
from app.models.intelligence import AIProviderKind, AITaskKind
from app.services.ai.base import (
    AICapabilities,
    AIProvider,
    AIProviderError,
    AIProviderStatus,
    AIProviderUnavailable,
    AIResponse,
    extract_json,
    json_token_budget,
)
from app.services.openrouter.client import OpenRouterError, extract_text
from app.services.openrouter.service import openrouter_service

logger = get_logger(__name__)


class OpenRouterAIProvider(AIProvider):
    """Moteur distant, limite aux modeles gratuits."""

    kind = AIProviderKind.OPENROUTER

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._text_model: str | None = None
        self._vision_model: str | None = None

    def update_models(self, text_model: str | None, vision_model: str | None) -> None:
        """Synchronise avec la selection du FreeModelSelector."""
        self._text_model = text_model
        self._vision_model = vision_model

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def configured(self) -> bool:
        return bool(self._enabled and openrouter_service.configured)

    async def status(self) -> AIProviderStatus:
        state = AIProviderStatus(
            kind=self.kind,
            configured=self.configured,
            model=self._text_model,
            vision_model=self._vision_model,
            capabilities=AICapabilities(
                text=True,
                json_mode=True,
                tools=True,
                vision=bool(self._vision_model),
                context_size=128000,
            ),
        )
        if not self._enabled:
            state.detail = "OpenRouter desactive dans les reglages."
            return state
        if not openrouter_service.configured:
            state.detail = "Aucune cle OpenRouter enregistree."
            return state

        breaker = openrouter_service.client.breaker
        if getattr(breaker, "is_open", False):
            state.error = "Coupe-circuit ouvert : trop d'echecs recents."
            return state

        state.available = bool(self._text_model)
        if not state.available:
            state.detail = "Aucun modele gratuit retenu pour le moment."
        return state

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
        if not self.configured:
            raise AIProviderUnavailable("OpenRouter non configure")

        max_tokens = json_token_budget(max_tokens, json_mode)
        vision = image_base64 is not None or task is AITaskKind.VISION
        # Un modele impose prime sur la selection automatique : c'est ainsi
        # que l'ensemble obtient deux avis reellement distincts.
        model = model or (self._vision_model if vision else self._text_model)
        if not model:
            raise AIProviderUnavailable(
                "Aucun modele gratuit disponible actuellement." if not vision
                else "Aucun modele vision gratuit disponible actuellement."
            )

        content: Any = prompt
        if image_base64:
            content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                },
            ]
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        started = time.monotonic()
        try:
            data = await openrouter_service.client.chat(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
        except OpenRouterError as exc:
            raise AIProviderError(str(exc)[:200]) from exc

        text = extract_text(data)
        latency = int((time.monotonic() - started) * 1000)
        payload = extract_json(text) if json_mode else None
        return AIResponse(
            provider=self.kind,
            model=model,
            text=text,
            latency_ms=latency,
            payload=payload,
            valid_json=payload is not None,
            raw_usage=data.get("usage") if isinstance(data, dict) else None,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        try:
            return await openrouter_service.client.list_models()
        except OpenRouterError:
            return []
