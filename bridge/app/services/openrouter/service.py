"""Facade OpenRouter : cle, modeles, appels et tracabilite."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger, mask_middle, register_secret
from app.config.settings import get_settings
from app.models.core import utcnow
from app.models.enums import ConnectionState
from app.models.trading import AiModelState, AiRequest
from app.services.events import EventType, event_bus
from app.services.openrouter.chart_ai import ChartAnalysis, analyze_chart
from app.services.openrouter.client import (
    OpenRouterAuthError,
    OpenRouterClient,
    OpenRouterError,
    OpenRouterRateLimited,
    OpenRouterUnavailable,
)
from app.services.openrouter.model_selector import NO_FREE_MODEL_MESSAGE, FreeModelSelector
from app.services.openrouter.signal_ai import parse_with_ai
from app.services.security.crypto import SECRET_OPENROUTER_API_KEY, SecretStore
from app.services.signals.models import ParsedSignal

logger = get_logger(__name__)


class OpenRouterService:
    """Point d'entree unique : conserve le coupe-circuit entre les requetes."""

    def __init__(self) -> None:
        self._client = OpenRouterClient(None)
        self._api_key: str = ""
        self._models_with_tools: set[str] = set()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    async def configure(self, session: AsyncSession) -> None:
        """Charge la cle depuis le coffre chiffre, sinon depuis l'environnement."""
        store = SecretStore(session)
        key = await store.get(SECRET_OPENROUTER_API_KEY)
        if not key:
            key = get_settings().openrouter_api_key.strip()
            if key:
                await store.set(SECRET_OPENROUTER_API_KEY, key)
        key = key or ""
        if key != self._api_key:
            self._api_key = key
            self._client = OpenRouterClient(key)
            register_secret(key)

    async def set_api_key(self, session: AsyncSession, api_key: str | None) -> None:
        store = SecretStore(session)
        await store.set(SECRET_OPENROUTER_API_KEY, api_key)
        self._api_key = (api_key or "").strip()
        self._client = OpenRouterClient(self._api_key)

    @property
    def client(self) -> OpenRouterClient:
        return self._client

    @property
    def configured(self) -> bool:
        return self._client.configured

    # ------------------------------------------------------------------
    # Etat et modeles
    # ------------------------------------------------------------------
    async def status(self, session: AsyncSession) -> dict[str, Any]:
        selector = FreeModelSelector(self._client, session)
        state = await selector.state()
        if not self.configured:
            connection = ConnectionState.NOT_CONFIGURED
        elif self._client.breaker.is_open:
            connection = ConnectionState.ERROR
        elif state.text_model_ok:
            connection = ConnectionState.CONNECTED
        else:
            connection = ConnectionState.DISCONNECTED
        return {
            "state": connection.value,
            "configured": self.configured,
            "apiKeyHint": await SecretStore(session).hint(SECRET_OPENROUTER_API_KEY),
            "autoMode": state.auto_mode,
            "textModel": state.text_model,
            "visionModel": state.vision_model,
            "preferredTextModel": state.preferred_text_model,
            "preferredVisionModel": state.preferred_vision_model,
            "textModelOk": state.text_model_ok,
            "visionModelOk": state.vision_model_ok,
            "textModelIsFree": True,
            "freeModels": state.free_models,
            "lastRefreshAt": state.last_refresh_at.isoformat() if state.last_refresh_at else None,
            "lastTestAt": state.last_test_at.isoformat() if state.last_test_at else None,
            "lastLatencyMs": state.last_latency_ms,
            "lastError": state.last_error,
            "circuitOpen": self._client.breaker.is_open,
            "circuitResetInSeconds": self._client.breaker.seconds_until_reset,
        }

    async def refresh_models(
        self, session: AsyncSession, force: bool = True, run_tests: bool = True
    ) -> AiModelState:
        settings = get_settings()
        selector = FreeModelSelector(self._client, session)
        state = await selector.refresh(
            force=force,
            preferred_text=settings.openrouter_preferred_text_model or None,
            preferred_vision=settings.openrouter_preferred_vision_model or None,
            run_tests=run_tests,
        )
        event_bus.publish(
            EventType.OPENROUTER_STATUS,
            {
                "textModel": state.text_model,
                "visionModel": state.vision_model,
                "ok": state.text_model_ok,
                "error": state.last_error,
            },
        )
        return state

    async def active_text_model(self, session: AsyncSession) -> str | None:
        state = await FreeModelSelector(self._client, session).state()
        return state.text_model

    async def active_vision_model(self, session: AsyncSession) -> str | None:
        state = await FreeModelSelector(self._client, session).state()
        return state.vision_model

    async def test_connection(self, session: AsyncSession) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Aucune cle OpenRouter configuree"}
        selector = FreeModelSelector(self._client, session)
        state = await selector.state()
        model = state.text_model
        if not model:
            state = await self.refresh_models(session, force=True, run_tests=True)
            model = state.text_model
        if not model:
            return {"ok": False, "error": NO_FREE_MODEL_MESSAGE}
        ok, latency, error = await selector.test_model(model)
        state.last_test_at = utcnow()
        state.text_model_ok = ok
        state.last_latency_ms = latency
        state.last_error = error
        session.add(state)
        await self._record_request(
            session, purpose="model_test", model=model, success=ok, latency_ms=latency, error=error
        )
        return {"ok": ok, "model": model, "latencyMs": latency, "error": error}

    # ------------------------------------------------------------------
    # Analyse de signaux
    # ------------------------------------------------------------------
    async def parse_signal(
        self, session: AsyncSession, text: str, signal_id: int | None = None
    ) -> tuple[ParsedSignal | None, str | None]:
        """Retourne (signal, erreur). Une erreur laisse le pipeline en NEEDS_REVIEW."""
        if not self.configured:
            return None, "Aucune cle OpenRouter configuree"

        selector = FreeModelSelector(self._client, session)
        state = await selector.state()
        model = state.text_model
        if not model:
            state = await selector.refresh(run_tests=False)
            model = state.text_model
        if not model:
            return None, NO_FREE_MODEL_MESSAGE

        use_tools = self._supports_tools(state, model)
        started = time.monotonic()
        try:
            signal, metadata = await parse_with_ai(self._client, model, text, use_tools=use_tools)
        except OpenRouterRateLimited as exc:
            await self._record_request(
                session, "signal_parse", model, False, int((time.monotonic() - started) * 1000),
                str(exc), signal_id, len(text),
            )
            return None, f"Quota OpenRouter atteint : {exc}"
        except (OpenRouterUnavailable, OpenRouterAuthError) as exc:
            await self._record_request(
                session, "signal_parse", model, False, int((time.monotonic() - started) * 1000),
                str(exc), signal_id, len(text),
            )
            return None, str(exc)
        except OpenRouterError as exc:
            await self._record_request(
                session, "signal_parse", model, False, int((time.monotonic() - started) * 1000),
                str(exc), signal_id, len(text),
            )
            return None, str(exc)

        latency = int((time.monotonic() - started) * 1000)
        await self._record_request(
            session,
            "signal_parse",
            str(metadata.get("model", model)),
            True,
            latency,
            None,
            signal_id,
            len(text),
        )
        return signal, None

    async def analyze_chart_image(
        self,
        session: AsyncSession,
        image_bytes: bytes,
        mime_type: str,
        instrument: str | None = None,
        question: str | None = None,
    ) -> ChartAnalysis:
        if not self.configured:
            raise OpenRouterAuthError("Aucune cle OpenRouter configuree")
        selector = FreeModelSelector(self._client, session)
        state = await selector.state()
        model = state.vision_model
        if not model:
            state = await selector.refresh(run_tests=False)
            model = state.vision_model
        if not model:
            raise OpenRouterError(NO_FREE_MODEL_MESSAGE)

        started = time.monotonic()
        try:
            analysis = await analyze_chart(
                self._client, model, image_bytes, mime_type, instrument=instrument, question=question
            )
        except OpenRouterError as exc:
            await self._record_request(
                session, "chart_analysis", model, False, int((time.monotonic() - started) * 1000), str(exc)
            )
            raise
        await self._record_request(
            session, "chart_analysis", analysis.model or model, True,
            int((time.monotonic() - started) * 1000), None, None, len(image_bytes),
        )
        return analysis

    # ------------------------------------------------------------------
    # Interne
    # ------------------------------------------------------------------
    def _supports_tools(self, state: AiModelState, model: str) -> bool:
        for entry in state.free_models or []:
            if entry.get("id") == model:
                return bool(entry.get("tools"))
        return False

    async def _record_request(
        self,
        session: AsyncSession,
        purpose: str,
        model: str,
        success: bool,
        latency_ms: int | None = None,
        error: str | None = None,
        signal_id: int | None = None,
        prompt_chars: int = 0,
    ) -> None:
        session.add(
            AiRequest(
                purpose=purpose,
                model=model,
                is_free_model=True,
                success=success,
                latency_ms=latency_ms,
                error=(error[:255] if error else None),
                signal_id=signal_id,
                prompt_chars=prompt_chars,
            )
        )
        await session.flush()

    def describe_key(self) -> str:
        return mask_middle(self._api_key)


openrouter_service = OpenRouterService()
