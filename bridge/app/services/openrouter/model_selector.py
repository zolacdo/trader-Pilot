"""Selection dynamique des modeles OpenRouter gratuits.

Les modeles gratuits apparaissent et disparaissent : le systeme ne doit jamais
dependre d'un identifiant fige. Un modele payant n'est JAMAIS choisi
automatiquement (CDC section 19).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import utcnow
from app.models.trading import AiModelState
from app.services.openrouter.client import (
    OpenRouterClient,
    OpenRouterError,
    context_length,
    extract_text,
    is_free_model,
    supports_tools,
    supports_vision,
)

logger = get_logger(__name__)

NO_FREE_MODEL_MESSAGE = "Aucun modele gratuit disponible actuellement."
MIN_CONTEXT_LENGTH = 8000

# Familles connues pour bien suivre une consigne d'extraction structuree.
_PREFERRED_FAMILIES = (
    "nvidia/",
    "deepseek/",
    "qwen/",
    "meta-llama/",
    "mistralai/",
    "google/gemini",
    "z-ai/",
    "moonshotai/",
)


@dataclass(slots=True)
class ModelCandidate:
    model_id: str
    free: bool
    vision: bool
    tools: bool
    context: int
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.model_id,
            "free": self.free,
            "vision": self.vision,
            "tools": self.tools,
            "context": self.context,
            "score": round(self.score, 2),
        }


def _family_bonus(model_id: str) -> float:
    lowered = model_id.lower()
    for index, family in enumerate(_PREFERRED_FAMILIES):
        if lowered.startswith(family):
            return 3.0 - index * 0.2
    return 0.0


def build_candidate(model: dict[str, Any], need_vision: bool = False) -> ModelCandidate:
    model_id = str(model.get("id", ""))
    free = is_free_model(model)
    vision = supports_vision(model)
    tools = supports_tools(model)
    ctx = context_length(model)

    score = 0.0
    score += _family_bonus(model_id)
    if tools:
        score += 2.0
    if ctx >= 32000:
        score += 1.5
    elif ctx >= MIN_CONTEXT_LENGTH:
        score += 0.5
    if need_vision and vision:
        score += 4.0
    if ":free" in model_id:
        score += 0.5
    return ModelCandidate(model_id=model_id, free=free, vision=vision, tools=tools, context=ctx, score=score)


def rank_free_models(models: list[dict[str, Any]], need_vision: bool = False) -> list[ModelCandidate]:
    """Classe uniquement les modeles gratuits repondant au besoin exprime."""
    candidates: list[ModelCandidate] = []
    for model in models:
        candidate = build_candidate(model, need_vision=need_vision)
        if not candidate.free:
            continue
        if need_vision and not candidate.vision:
            continue
        if candidate.context and candidate.context < 4000:
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: (item.score, item.context), reverse=True)
    return candidates


class FreeModelSelector:
    """Maintient l'etat des modeles actifs et bascule vers un repli gratuit."""

    def __init__(self, client: OpenRouterClient, session: AsyncSession) -> None:
        self._client = client
        self._session = session

    async def state(self) -> AiModelState:
        state = await self._session.get(AiModelState, 1)
        if state is None:
            state = AiModelState(id=1)
            self._session.add(state)
            await self._session.flush()
        return state

    async def refresh(
        self,
        force: bool = False,
        preferred_text: str | None = None,
        preferred_vision: str | None = None,
        run_tests: bool = True,
    ) -> AiModelState:
        """Recharge la liste, verifie le modele prefere, choisit un repli si besoin."""
        state = await self.state()
        if preferred_text:
            state.preferred_text_model = preferred_text
        if preferred_vision:
            state.preferred_vision_model = preferred_vision

        try:
            models = await self._client.list_models(force_refresh=force)
        except OpenRouterError as exc:
            state.last_error = str(exc)[:255]
            state.text_model_ok = False
            state.vision_model_ok = False
            state.last_refresh_at = utcnow()
            self._session.add(state)
            await self._session.flush()
            return state

        text_candidates = rank_free_models(models, need_vision=False)
        vision_candidates = rank_free_models(models, need_vision=True)
        state.free_models = [candidate.to_dict() for candidate in text_candidates[:40]]
        state.last_refresh_at = utcnow()
        state.last_error = None

        if not state.auto_mode:
            # Mode manuel : on verifie seulement que le choix reste gratuit.
            state.text_model_ok = self._is_free(state.text_model, text_candidates)
            state.vision_model_ok = self._is_free(state.vision_model, vision_candidates)
            self._session.add(state)
            await self._session.flush()
            return state

        state.text_model = await self._pick(
            preferred=state.preferred_text_model,
            candidates=text_candidates,
            run_tests=run_tests,
            state=state,
            kind="texte",
        )
        state.text_model_ok = state.text_model is not None

        state.vision_model = await self._pick(
            preferred=state.preferred_vision_model,
            candidates=vision_candidates,
            run_tests=False,  # un test vision consomme un quota image inutilement
            state=state,
            kind="vision",
        )
        state.vision_model_ok = state.vision_model is not None

        if state.text_model is None:
            state.last_error = NO_FREE_MODEL_MESSAGE
        state.updated_at = utcnow()
        self._session.add(state)
        await self._session.flush()
        return state

    @staticmethod
    def _is_free(model_id: str | None, candidates: list[ModelCandidate]) -> bool:
        if not model_id:
            return False
        return any(candidate.model_id == model_id for candidate in candidates)

    async def _pick(
        self,
        preferred: str | None,
        candidates: list[ModelCandidate],
        run_tests: bool,
        state: AiModelState,
        kind: str,
    ) -> str | None:
        if not candidates:
            logger.warning("%s : %s", kind, NO_FREE_MODEL_MESSAGE)
            return None

        ordered = list(candidates)
        if preferred:
            match = next((c for c in ordered if c.model_id == preferred), None)
            if match is not None:
                ordered.remove(match)
                ordered.insert(0, match)
            else:
                logger.info("Modele prefere %s indisponible ou payant : repli gratuit", preferred)

        if not run_tests:
            return ordered[0].model_id

        for candidate in ordered[:3]:
            ok, latency, error = await self.test_model(candidate.model_id)
            state.last_test_at = utcnow()
            if ok:
                state.last_latency_ms = latency
                return candidate.model_id
            logger.info("Modele %s ecarte : %s", candidate.model_id, error)
        # Aucun test concluant : on garde le meilleur candidat gratuit sans
        # pretendre qu'il a ete valide.
        state.last_error = "Aucun modele gratuit n'a repondu au test"
        return ordered[0].model_id

    async def test_model(self, model_id: str) -> tuple[bool, int | None, str | None]:
        """Ping minimal du modele. Retourne (succes, latence_ms, erreur)."""
        started = time.monotonic()
        try:
            payload = await self._client.chat(
                model=model_id,
                messages=[
                    {"role": "system", "content": "Reply with the single word OK."},
                    {"role": "user", "content": "ping"},
                ],
                max_tokens=8,
                timeout=25.0,
            )
        except OpenRouterError as exc:
            return False, None, str(exc)[:200]
        latency = int((time.monotonic() - started) * 1000)
        text = extract_text(payload).strip()
        if not text:
            return False, latency, "Reponse vide"
        return True, latency, None

    async def set_manual(self, text_model: str | None, vision_model: str | None) -> AiModelState:
        state = await self.state()
        state.auto_mode = False
        state.text_model = text_model
        state.vision_model = vision_model
        state.updated_at = utcnow()
        self._session.add(state)
        await self._session.flush()
        return state

    async def set_auto(self) -> AiModelState:
        state = await self.state()
        state.auto_mode = True
        state.updated_at = utcnow()
        self._session.add(state)
        await self._session.flush()
        return state
