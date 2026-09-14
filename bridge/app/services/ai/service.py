"""Service d'intelligence hybride : point d'entree unique du Bridge.

Il assemble les deux moteurs, le routeur, le mode ensemble et la mesure de
fiabilite. Le reste de l'application n'appelle que ce service : elle ignore
lequel des deux moteurs a repondu.

Regle de securite (CDC2 section 100) : si aucune intelligence n'est
disponible, les analyses deterministes continuent, mais une decision qui
exige l'IA devient NEEDS_REVIEW. Jamais un trade sans regle.
"""

from __future__ import annotations

from typing import Any

from app.config.logging_config import get_logger
from app.database.session import session_scope
from app.models.enums import Direction
from app.models.intelligence import (
    AIConsensusRecord,
    AIProviderKind,
    AISettings,
    AITaskKind,
    ConsensusOutcome,
)
from app.repositories import ai_repo
from app.services.ai.base import AIProviderUnavailable
from app.services.ai.ensemble.service import (
    AIConsensusEngine,
    AIEnsembleService,
    ConsensusResult,
    ProviderOpinion,
    opinion_from_response,
)
from app.services.ai.openai_compatible import (
    KNOWN_ENDPOINTS,
    RemoteConfig,
    google_provider,
    groq_provider,
)
from app.services.ai.openrouter_provider import OpenRouterAIProvider
from app.services.ai.router.router import AIRouter, RoutedResponse
from app.services.events import EventType, event_bus
from app.services.openrouter.service import openrouter_service

logger = get_logger(__name__)


class AIService:
    """Facade de l'intelligence hybride."""

    def __init__(self) -> None:
        self._settings = AISettings()
        self._remote = OpenRouterAIProvider(enabled=True)
        # Moteurs compatibles OpenAI, configures depuis les reglages.
        self._groq = groq_provider
        self._google = google_provider
        self._router = AIRouter(self._remote, extras=(self._groq, self._google))
        self._ensemble = AIEnsembleService(self._router)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @property
    def settings(self) -> AISettings:
        return self._settings

    @property
    def router(self) -> AIRouter:
        return self._router

    async def configure(self, session) -> AISettings:
        """Recharge les reglages et synchronise les moteurs."""
        settings = await ai_repo.get_settings(session)
        self._settings = settings
        self._remote.set_enabled(settings.openrouter_enabled)
        await self._configure_compatibles(session, settings)
        await self._sync_remote_models(session)

        # Fiabilite mesuree : le routeur s'en sert pour arbitrer.
        for metric in await ai_repo.list_metrics(session):
            self._router.record_reliability(
                metric.provider, metric.task, metric.success_rate, metric.calls
            )
        return settings

    async def _configure_compatibles(self, session, settings: AISettings) -> None:
        """Applique les reglages des moteurs Groq et Google AI Studio.

        Leurs cles vivent dans le coffre chiffre : elles ne transitent ni par
        les reglages affichables, ni par l'API, ni par les journaux.
        """
        from app.services.security.crypto import (
            SECRET_GOOGLE_API_KEY,
            SECRET_GROQ_API_KEY,
            SecretStore,
        )

        coffre = SecretStore(session)
        for fournisseur, actif, modele, cle_secret in (
            (self._groq, settings.groq_enabled, settings.groq_model, SECRET_GROQ_API_KEY),
            (
                self._google,
                settings.google_enabled,
                settings.google_model,
                SECRET_GOOGLE_API_KEY,
            ),
        ):
            try:
                cle = await coffre.get(cle_secret) or ""
            except Exception as exc:
                logger.info("Cle %s illisible : %s", cle_secret, type(exc).__name__)
                cle = ""
            fournisseur.configure(
                RemoteConfig(
                    enabled=bool(actif),
                    base_url=KNOWN_ENDPOINTS.get(fournisseur.kind, ""),
                    api_key=cle,
                    model=modele or "",
                )
            )

    async def _sync_remote_models(self, session) -> None:
        """Transmet au fournisseur distant les modeles gratuits retenus.

        Sans ce pont, le fournisseur gardait ``_text_model = None`` a vie :
        il se declarait indisponible, le routeur l'ecartait, et toute la
        couche hybride — consensus, ensemble, revue d'opportunite — restait
        muette alors qu'un modele gratuit etait bel et bien selectionne.
        """
        if not openrouter_service.configured:
            return
        try:
            texte = await openrouter_service.active_text_model(session)
            vision = await openrouter_service.active_vision_model(session)
        except Exception as exc:
            logger.info("Modeles OpenRouter non synchronises : %s", exc)
            return
        self.sync_openrouter_models(texte, vision)

    def sync_openrouter_models(self, text_model: str | None, vision_model: str | None) -> None:
        self._remote.update_models(text_model, vision_model)

    # ------------------------------------------------------------------
    # Etat
    # ------------------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        """Etat des moteurs d'intelligence (CDC2 section 96)."""
        remote = await self._remote.status()
        groq = await self._groq.status()
        google = await self._google.status()
        # « Aucune intelligence » signifie qu'AUCUN des trois ne repond : un
        # quota epuise chez l'un ne doit pas faire croire a une panne generale.
        both_offline = not (remote.available or groq.available or google.available)
        return {
            "mode": self._settings.mode.value,
            "openrouter": remote.to_dict(),
            "providers": {
                "openrouter": remote.to_dict(),
                "groq": groq.to_dict(),
                "google": google.to_dict(),
            },
            "ensembleEnabled": self._settings.ensemble_enabled,
            "requireConsensus": self._settings.require_consensus_for_auto_trade,
            "disagreementBehaviour": self._settings.disagreement_behaviour,
            "aiTradingEnabled": self._settings.ai_trading_enabled,
            "shadowMode": self._settings.shadow_mode,
            "anyAvailable": not both_offline,
            "detail": (
                "Intelligence indisponible : les analyses deterministes continuent, "
                "mais toute decision exigeant l'IA passe en revue manuelle."
                if both_offline
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Appels
    # ------------------------------------------------------------------
    async def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        task: AITaskKind = AITaskKind.MARKET_ANALYSIS,
        max_tokens: int = 800,
        timeout: float | None = None,
        image_base64: str | None = None,
        large_context: bool = False,
    ) -> RoutedResponse | None:
        """Analyse structuree via le moteur le mieux adapte.

        Retourne ``None`` lorsque aucune intelligence n'a pu repondre :
        l'appelant doit alors se rabattre sur le deterministe ou refuser.
        """
        try:
            routed = await self._router.complete(
                self._settings,
                prompt,
                system=system,
                task=task,
                json_mode=True,
                max_tokens=max_tokens,
                timeout=timeout,
                image_base64=image_base64,
                large_context=large_context,
            )
        except AIProviderUnavailable as exc:
            logger.info("Aucune IA disponible pour %s : %s", task.value, exc)
            await self._trace_routing(task, None, False, str(exc), None, success=False)
            return None

        # La latence mesuree nourrit les choix suivants : a fiabilite egale,
        # le routeur preferera le moteur qui repond vite.
        self._router.record_latency(routed.provider, task, float(routed.response.latency_ms))
        await self._trace_routing(
            task,
            routed.provider,
            routed.fallback_used,
            routed.routing.reason,
            routed.response.latency_ms,
            success=True,
        )
        await self._trace_call(routed, task)
        return routed

    async def consensus(
        self,
        prompt: str,
        *,
        system: str | None = None,
        task: AITaskKind = AITaskKind.OPPORTUNITY_REVIEW,
        deterministic_direction: Direction | None = None,
        deterministic_score: float | None = None,
        decision_id: int | None = None,
        max_tokens: int = 700,
    ) -> ConsensusResult:
        """Confronte les deux moteurs puis recalibre sur les mesures reelles."""
        result = await self._ensemble.analyse(
            self._settings, prompt, system=system, task=task, max_tokens=max_tokens
        )
        result = AIConsensusEngine.recalibrate(
            result, deterministic_direction, deterministic_score
        )
        await self._persist_consensus(result, task, decision_id)

        if result.outcome is ConsensusOutcome.DISAGREEMENT:
            event_bus.publish(
                EventType.AI_DISAGREEMENT,
                {"task": task.value, "detail": result.detail},
            )
        event_bus.publish(
            EventType.AI_CONSENSUS_EVENT,
            {"task": task.value, "outcome": result.outcome.value},
        )
        return result

    def requires_manual_review(self, result: ConsensusResult) -> bool:
        """Le consensus autorise-t-il une execution automatique ?"""
        if not self._settings.require_consensus_for_auto_trade:
            return False
        return result.blocks_auto_trade or result.outcome is ConsensusOutcome.PARTIAL_CONSENSUS

    # ------------------------------------------------------------------
    # Traces
    # ------------------------------------------------------------------
    async def _trace_routing(
        self,
        task: AITaskKind,
        chosen: AIProviderKind | None,
        fallback: bool,
        reason: str | None,
        latency_ms: int | None,
        success: bool,
    ) -> None:
        try:
            async with session_scope() as session:
                await ai_repo.record_routing(
                    session,
                    task,
                    self._settings.mode,
                    chosen,
                    fallback_used=fallback,
                    reason=reason,
                    latency_ms=latency_ms,
                    success=success,
                )
        except Exception:  # une trace ne doit jamais casser une analyse
            logger.debug("Trace de routage non enregistree")

    async def _trace_call(self, routed: RoutedResponse, task: AITaskKind) -> None:
        """Met a jour la fiabilite du moteur retenu, et celle des moteurs ecartes."""
        try:
            async with session_scope() as session:
                await ai_repo.record_call(
                    session,
                    routed.provider,
                    task,
                    model=routed.response.model,
                    success=True,
                    valid_json=routed.response.valid_json,
                    latency_ms=routed.response.latency_ms,
                )
                for kind, reason in routed.attempts:
                    await ai_repo.record_call(
                        session,
                        kind,
                        task,
                        success=False,
                        timeout="elai" in reason.lower(),
                        error=reason,
                    )
        except Exception:
            logger.debug("Metrique IA non enregistree")

    async def _persist_consensus(
        self, result: ConsensusResult, task: AITaskKind, decision_id: int | None
    ) -> None:
        # Les deux avis viennent du meme fournisseur : c'est leur ORDRE
        # d'interrogation qui les distingue, le premier etant le modele par
        # defaut et le second celui choisi dans les reglages.
        avis = list(result.opinions)
        primaire = avis[0] if avis else None
        secondaire = avis[1] if len(avis) > 1 else None
        record = AIConsensusRecord(
            decision_id=decision_id,
            task=task,
            outcome=result.outcome,
            primary_model=primaire.model if primaire else None,
            primary_direction=primaire.direction if primaire else None,
            primary_confidence=primaire.confidence if primaire else None,
            primary_latency_ms=primaire.latency_ms if primaire else None,
            primary_summary=primaire.summary if primaire else None,
            secondary_model=secondaire.model if secondaire else None,
            secondary_direction=secondaire.direction if secondaire else None,
            secondary_confidence=secondaire.confidence if secondaire else None,
            secondary_latency_ms=secondaire.latency_ms if secondaire else None,
            secondary_summary=secondaire.summary if secondaire else None,
            final_direction=result.direction,
            final_confidence=result.confidence,
            detail=result.detail[:500],
        )
        try:
            async with session_scope() as session:
                await ai_repo.save_consensus(session, record)
                if result.outcome is ConsensusOutcome.DISAGREEMENT:
                    await ai_repo.record_disagreement(session, task)
        except Exception:
            logger.debug("Consensus non enregistre")


ai_service = AIService()

__all__ = ["AIService", "ProviderOpinion", "ai_service", "opinion_from_response"]
