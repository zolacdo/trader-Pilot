"""AIRouter : prepare et execute un appel d'intelligence (CDC2 sections 4, 9, 10).

Le moteur local a ete retire : il imposait d'heberger un serveur d'inference
sur une machine qui fait deja tourner MetaTrader 5, PostgreSQL et le Bridge.
Trois moteurs DISTANTS le remplacent -- OpenRouter, Groq, Google AI Studio.

Ce qui justifie d'en avoir trois n'est pas la variete : c'est que leurs quotas
sont INDEPENDANTS. OpenRouter plafonne les modeles gratuits a 50 requetes par
jour sans credit achete, plafond atteint des la mi-journee. Le routeur essaie
donc les moteurs dans l'ordre et passe au suivant quand l'un est a sec.

La trace du chemin suivi est conservee parce que c'est elle qui permet de dire
POURQUOI une analyse n'a pas eu lieu. Un appelant ne doit jamais avoir a
deviner si l'IA s'est tue ou n'a jamais ete sollicitee.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config.logging_config import get_logger
from app.models.intelligence import AIMode, AIProviderKind, AISettings, AITaskKind
from app.services.ai.base import (
    AIProvider,
    AIProviderError,
    AIProviderUnavailable,
    AIResponse,
)

logger = get_logger(__name__)

# En dessous de ce taux de succes, un moteur est signale comme defaillant.
RELIABILITY_FLOOR = 0.5
MIN_CALLS_FOR_RELIABILITY = 8


@dataclass(slots=True)
class RoutingDecision:
    """Ce que le routeur a choisi, et pourquoi."""

    order: list[AIProviderKind]
    reason: str
    mode: AIMode

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": [kind.value for kind in self.order],
            "reason": self.reason,
            "mode": self.mode.value,
        }


@dataclass(slots=True)
class RoutedResponse:
    """Reponse obtenue, avec la trace du chemin suivi."""

    response: AIResponse
    provider: AIProviderKind
    fallback_used: bool
    routing: RoutingDecision
    attempts: list[tuple[AIProviderKind, str]]


class AIRouter:
    """Choisit un moteur, l'appelle, et conserve la trace de ce qui s'est passe."""

    def __init__(self, remote: AIProvider, extras: tuple[AIProvider, ...] = ()) -> None:
        self._remote = remote
        # Fournisseurs supplementaires, indexes par nature. Leur interet est
        # d'avoir des quotas INDEPENDANTS : quand l'un est a sec, les autres
        # repondent encore.
        self._extras: dict[AIProviderKind, AIProvider] = {
            fournisseur.kind: fournisseur for fournisseur in extras
        }
        # Fiabilite mesuree, alimentee par le service d'evaluation.
        self._reliability: dict[tuple[AIProviderKind, AITaskKind], float] = {}
        self._calls: dict[tuple[AIProviderKind, AITaskKind], int] = {}
        # Latence moyenne observee, en millisecondes.
        self._latency: dict[tuple[AIProviderKind, AITaskKind], float] = {}

    def provider(self, kind: AIProviderKind) -> AIProvider:
        """Moteur correspondant, OpenRouter par defaut."""
        return self._extras.get(kind, self._remote)

    def available_kinds(self, settings: AISettings) -> list[AIProviderKind]:
        """Moteurs reellement joignables, dans l'ordre de preference.

        L'ordre compte : OpenRouter d'abord parce que sa selection de modeles
        gratuits est deja eprouvee, puis les autres, dont le seul role est de
        rester disponibles quand le premier a epuise son quota.
        """
        kinds: list[AIProviderKind] = []
        if settings.openrouter_enabled and self._remote.configured:
            kinds.append(AIProviderKind.OPENROUTER)
        for kind, fournisseur in self._extras.items():
            if fournisseur.configured:
                kinds.append(kind)
        return kinds

    def record_reliability(
        self, kind: AIProviderKind, task: AITaskKind, success_rate: float, calls: int
    ) -> None:
        self._reliability[(kind, task)] = success_rate
        self._calls[(kind, task)] = calls

    def record_latency(self, kind: AIProviderKind, task: AITaskKind, latency_ms: float) -> None:
        """Moyenne glissante de la latence, alimentee par chaque appel reussi."""
        cle = (kind, task)
        actuelle = self._latency.get(cle)
        self._latency[cle] = latency_ms if actuelle is None else (actuelle * 0.7 + latency_ms * 0.3)

    def _is_reliable(self, kind: AIProviderKind, task: AITaskKind) -> bool:
        """Signale un moteur defaillant sans jamais l'exclure.

        L'exclure reviendrait a se priver d'un quota encore disponible pour une
        mesure qui peut n'etre qu'un mauvais moment. Le repli sur le moteur
        suivant suffit ; la trace dit ce qui a ete observe.
        """
        calls = self._calls.get((kind, task), 0)
        if calls < MIN_CALLS_FOR_RELIABILITY:
            return True
        return self._reliability.get((kind, task), 1.0) >= RELIABILITY_FLOOR

    # ------------------------------------------------------------------
    # Choix de l'ordre d'appel
    # ------------------------------------------------------------------
    def plan(
        self,
        settings: AISettings,
        task: AITaskKind,
        *,
        needs_vision: bool = False,
        large_context: bool = False,
    ) -> RoutingDecision:
        """Ordre des moteurs a essayer, du prefere au repli."""
        # Ni la taille du contexte ni le besoin de vision n'arbitrent : c'est
        # le modele choisi qui sait s'il peut repondre, et il le dira lui-meme
        # en echouant. Une supposition ici couterait un moteur pour rien.
        del large_context, needs_vision
        mode = settings.mode

        ordre = self.available_kinds(settings)
        if not ordre:
            return RoutingDecision([], "Aucun moteur configure et actif", mode)

        noms = ", ".join(kind.value for kind in ordre)
        reason = f"Moteurs joignables : {noms}"
        if not self._is_reliable(ordre[0], task):
            # On appelle quand meme : mieux vaut un moteur imparfait que rien.
            reason += " (fiabilite du premier sous le seuil sur cette tache)"

        return RoutingDecision(ordre, reason, mode)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    async def complete(
        self,
        settings: AISettings,
        prompt: str,
        *,
        system: str | None = None,
        task: AITaskKind = AITaskKind.MARKET_ANALYSIS,
        json_mode: bool = True,
        max_tokens: int = 800,
        timeout: float | None = None,
        image_base64: str | None = None,
        large_context: bool = False,
    ) -> RoutedResponse:
        """Interroge le moteur.

        Leve ``AIProviderUnavailable`` quand il n'aboutit pas : c'est alors a
        l'appelant de decider, et jamais de trader sans regle (CDC2 section 100).
        """
        routing = self.plan(
            settings, task, needs_vision=image_base64 is not None, large_context=large_context
        )
        if not routing.order:
            raise AIProviderUnavailable(
                f"Aucun moteur d'intelligence artificielle disponible : {routing.reason}."
            )

        attempts: list[tuple[AIProviderKind, str]] = []
        for index, kind in enumerate(routing.order):
            provider = self.provider(kind)
            try:
                response = await provider.complete(
                    prompt,
                    system=system,
                    task=task,
                    json_mode=json_mode,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    image_base64=image_base64,
                )
            except AIProviderError as exc:
                message = str(exc)[:160]
                attempts.append((kind, message))
                logger.info("Moteur %s ecarte pour %s : %s", kind.value, task.value, message)
                continue

            if json_mode and not response.valid_json:
                attempts.append((kind, "JSON invalide"))
                logger.info("Moteur %s : JSON invalide pour %s", kind.value, task.value)
                continue

            return RoutedResponse(
                response=response,
                provider=kind,
                fallback_used=index > 0,
                routing=routing,
                attempts=attempts,
            )

        detail = " | ".join(f"{kind.value}: {reason}" for kind, reason in attempts)
        raise AIProviderUnavailable(f"Aucun moteur n'a pu repondre. {detail}")
