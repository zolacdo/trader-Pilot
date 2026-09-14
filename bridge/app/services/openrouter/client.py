"""Client HTTP OpenRouter avec coupe-circuit et gestion des quotas.

Les modeles gratuits sont souvent indisponibles ou limites. Le client ne doit
jamais boucler sur des erreurs : il ouvre un coupe-circuit et laisse le parser
deterministe continuer seul (CDC section 73).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config.logging_config import get_logger
from app.config.settings import APP_VERSION

logger = get_logger(__name__)

API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 45.0
MODELS_CACHE_TTL = 900.0  # 15 minutes


class OpenRouterError(RuntimeError):
    """Erreur generique OpenRouter."""


class OpenRouterUnavailable(OpenRouterError):
    """Service indisponible : coupe-circuit ouvert, 5xx ou timeout."""


class OpenRouterRateLimited(OpenRouterError):
    """Quota atteint (HTTP 429)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class OpenRouterAuthError(OpenRouterError):
    """Cle absente ou invalide (HTTP 401/403)."""


@dataclass
class CircuitBreaker:
    """Coupe-circuit simple : N echecs consecutifs ouvrent le circuit."""

    failure_threshold: int = 4
    reset_after_seconds: float = 300.0
    failures: int = 0
    opened_at: float | None = field(default=None)

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.reset_after_seconds:
            self.reset()
            return False
        return True

    @property
    def seconds_until_reset(self) -> int:
        if self.opened_at is None:
            return 0
        remaining = self.reset_after_seconds - (time.monotonic() - self.opened_at)
        return max(0, int(remaining))

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold and self.opened_at is None:
            self.opened_at = time.monotonic()
            logger.warning(
                "Coupe-circuit OpenRouter ouvert pour %ss apres %s echecs",
                int(self.reset_after_seconds),
                self.failures,
            )

    def reset(self) -> None:
        self.failures = 0
        self.opened_at = None


def is_free_model(model: dict[str, Any]) -> bool:
    """Un modele est gratuit si toutes ses composantes de prix valent zero."""
    model_id = str(model.get("id", ""))
    pricing = model.get("pricing") or {}
    values: list[float] = []
    for key in ("prompt", "completion", "request", "image", "input_cache_read", "input_cache_write"):
        raw = pricing.get(key)
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            return False
    if not values:
        return model_id.endswith(":free")
    return all(value <= 0 for value in values)


def supports_vision(model: dict[str, Any]) -> bool:
    architecture = model.get("architecture") or {}
    modalities = architecture.get("input_modalities") or []
    if isinstance(modalities, list) and "image" in modalities:
        return True
    modality = str(architecture.get("modality", ""))
    return "image" in modality.split("->")[0]


def supports_tools(model: dict[str, Any]) -> bool:
    parameters = model.get("supported_parameters") or []
    return isinstance(parameters, list) and "tools" in parameters


def context_length(model: dict[str, Any]) -> int:
    try:
        return int(model.get("context_length") or 0)
    except (TypeError, ValueError):
        return 0


class OpenRouterClient:
    """Client minimal : liste des modeles et completions de chat."""

    def __init__(self, api_key: str | None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._api_key = (api_key or "").strip()
        self._timeout = timeout
        self.breaker = CircuitBreaker()
        self._models_cache: list[dict[str, Any]] = []
        self._models_cached_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/tradepilot",
            "X-Title": f"TradePilot {APP_VERSION}",
        }

    def _ensure_ready(self) -> None:
        if not self.configured:
            raise OpenRouterAuthError("Aucune cle OpenRouter configuree")
        if self.breaker.is_open:
            raise OpenRouterUnavailable(
                f"OpenRouter temporairement suspendu ({self.breaker.seconds_until_reset}s restantes)"
            )

    async def list_models(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Liste des modeles OpenRouter, mise en cache 15 minutes."""
        async with self._lock:
            fresh = time.monotonic() - self._models_cached_at < MODELS_CACHE_TTL
            if self._models_cache and fresh and not force_refresh:
                return self._models_cache
        self._ensure_ready()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{API_BASE}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            self.breaker.record_failure()
            raise OpenRouterUnavailable(f"Liste des modeles injoignable : {exc}") from exc

        self._raise_for_status(response)
        payload = response.json()
        models = payload.get("data") or []
        async with self._lock:
            self._models_cache = models
            self._models_cached_at = time.monotonic()
        self.breaker.record_success()
        return models

    async def free_models(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        return [model for model in await self.list_models(force_refresh) if is_free_model(model)]

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        max_tokens: int = 800,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Appelle /chat/completions. Une seule tentative : pas de boucle de retry."""
        self._ensure_ready()
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            if tool_choice is not None:
                body["tool_choice"] = tool_choice

        try:
            async with httpx.AsyncClient(timeout=timeout or self._timeout) as client:
                response = await client.post(
                    f"{API_BASE}/chat/completions", headers=self._headers(), json=body
                )
        except httpx.TimeoutException as exc:
            self.breaker.record_failure()
            raise OpenRouterUnavailable(f"Delai depasse pour {model}") from exc
        except httpx.HTTPError as exc:
            self.breaker.record_failure()
            raise OpenRouterUnavailable(f"Erreur reseau OpenRouter : {exc}") from exc

        self._raise_for_status(response)
        self.breaker.record_success()
        return response.json()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        detail = self._error_detail(response)
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            self.breaker.record_failure()
            raise OpenRouterRateLimited(
                f"Quota OpenRouter atteint : {detail}",
                retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status_code in {401, 403}:
            raise OpenRouterAuthError(f"Cle OpenRouter refusee : {detail}")
        if response.status_code == 404:
            raise OpenRouterError(f"Modele introuvable : {detail}")
        if response.status_code >= 500:
            self.breaker.record_failure()
            raise OpenRouterUnavailable(f"OpenRouter indisponible ({response.status_code}) : {detail}")
        raise OpenRouterError(f"Erreur OpenRouter {response.status_code} : {detail}")

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:200]
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message", ""))[:200]
        return str(error or payload)[:200]


def extract_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or []
    if not choices:
        raise OpenRouterError("Reponse OpenRouter sans choix")
    return choices[0].get("message") or {}


def extract_text(payload: dict[str, Any]) -> str:
    message = extract_message(payload)
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # format multimodal
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "\n".join(part for part in parts if part)
    return ""
