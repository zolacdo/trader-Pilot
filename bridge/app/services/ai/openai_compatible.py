"""Moteur distant parlant le dialecte OpenAI (CDC2 sections 4 et 8).

Groq et Google AI Studio exposent tous deux `/chat/completions` au format
OpenAI. Plutot que d'ecrire deux clients presque identiques, on ecrit celui-ci
une fois et on le configure deux fois.

Pourquoi les ajouter : OpenRouter plafonne les modeles gratuits a 50 requetes
par jour sans credit achete. Ce plafond etait atteint des le milieu de la
journee, et la confrontation a deux avis devenait impossible -- le second
modele echouait systematiquement. Deux fournisseurs INDEPENDANTS, c'est deux
quotas independants et deux modes de panne independants : c'est ce qui rend un
desaccord informatif plutot qu'accidentel.

Rien n'est code en dur : adresse, modele et cle viennent des reglages. La cle
n'est jamais journalisee ni renvoyee par l'API.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config.logging_config import get_logger, register_secret
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

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 45.0

# Adresses connues. L'utilisateur peut en saisir une autre : tout serveur
# parlant le dialecte OpenAI convient.
KNOWN_ENDPOINTS: dict[AIProviderKind, str] = {
    AIProviderKind.GROQ: "https://api.groq.com/openai/v1",
    AIProviderKind.GOOGLE: "https://generativelanguage.googleapis.com/v1beta/openai",
}

# Modeles par defaut, verifies par un appel reel le 12/09/2026 et remplacables
# dans les reglages. Attention cote Google : sur la couche compatible OpenAI,
# `gemini-2.5-flash` et `models/gemini-2.5-flash` renvoient tous deux 404 ;
# seul l'alias `gemini-flash-latest` repond.
DEFAULT_MODELS: dict[AIProviderKind, str] = {
    AIProviderKind.GROQ: "openai/gpt-oss-120b",
    AIProviderKind.GOOGLE: "gemini-flash-latest",
}


@dataclass(slots=True)
class RemoteConfig:
    """Ce qu'il faut pour joindre un moteur compatible OpenAI."""

    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.base_url.strip() and self.api_key.strip())


class OpenAICompatibleProvider(AIProvider):
    """Client d'un serveur distant au format OpenAI."""

    def __init__(self, kind: AIProviderKind, label: str) -> None:
        self.kind = kind
        self._label = label
        self._config = RemoteConfig()
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def configure(self, config: RemoteConfig) -> None:
        """Applique les reglages. La cle est masquee dans les journaux."""
        self._config = config
        if config.api_key:
            register_secret(config.api_key)

    @property
    def label(self) -> str:
        return self._label

    @property
    def model(self) -> str:
        return self._config.model.strip() or DEFAULT_MODELS.get(self.kind, "")

    @property
    def configured(self) -> bool:
        return self._config.ready

    # ------------------------------------------------------------------
    # Etat
    # ------------------------------------------------------------------
    async def status(self) -> AIProviderStatus:
        state = AIProviderStatus(
            kind=self.kind,
            configured=self.configured,
            model=self.model or None,
            capabilities=AICapabilities(text=True, json_mode=True, context_size=128000),
        )
        if not self._config.enabled:
            state.detail = f"{self._label} desactive dans les reglages."
            return state
        if not self._config.api_key.strip():
            state.detail = f"Aucune cle {self._label} enregistree."
            return state
        if not self._config.base_url.strip():
            state.detail = f"Aucune adresse pour {self._label}."
            return state

        state.available = bool(self.model)
        if not state.available:
            state.detail = "Aucun modele choisi."
        state.error = self._last_error
        return state

    # ------------------------------------------------------------------
    # Appel
    # ------------------------------------------------------------------
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
        del task, image_base64  # ces moteurs sont utilises en texte seul
        if not self.configured:
            raise AIProviderUnavailable(f"{self._label} non configure")

        cible = (model or self.model).strip()
        if not cible:
            raise AIProviderUnavailable(f"Aucun modele choisi pour {self._label}")

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        corps: dict[str, Any] = {
            "model": cible,
            "messages": messages,
            "max_tokens": json_token_budget(max_tokens, json_mode),
            "temperature": temperature,
        }
        if json_mode:
            # Les deux fournisseurs acceptent ce mode ; s'il est refuse, la
            # reponse reste du texte et `extract_json` s'en debrouille.
            corps["response_format"] = {"type": "json_object"}

        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        debut = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=timeout or self._config.timeout_seconds
            ) as client:
                reponse = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=corps,
                )
        except httpx.HTTPError as exc:
            self._last_error = f"{type(exc).__name__}"
            raise AIProviderError(f"{self._label} injoignable : {type(exc).__name__}") from exc

        if reponse.status_code >= 400:
            detail = _detail_erreur(reponse)
            self._last_error = detail
            # Le quota et l'authentification ne se corrigent pas en reessayant :
            # on le dit clairement plutot que de laisser croire a un incident.
            raise AIProviderError(f"{self._label} a refuse ({reponse.status_code}) : {detail}")

        self._last_error = None
        donnees = reponse.json()
        texte = _extraire_texte(donnees)
        latence = int((time.monotonic() - debut) * 1000)
        charge = extract_json(texte) if json_mode else None
        return AIResponse(
            provider=self.kind,
            model=cible,
            text=texte,
            latency_ms=latence,
            payload=charge,
            valid_json=charge is not None,
            raw_usage=donnees.get("usage") if isinstance(donnees, dict) else None,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        """Modeles annonces par le serveur, pour aider au choix."""
        if not self.configured:
            return []
        url = f"{self._config.base_url.rstrip('/')}/models"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                reponse = await client.get(
                    url, headers={"Authorization": f"Bearer {self._config.api_key}"}
                )
                reponse.raise_for_status()
                donnees = reponse.json()
        except httpx.HTTPError as exc:
            raise AIProviderError(
                f"Liste des modeles {self._label} indisponible : {type(exc).__name__}"
            ) from exc
        entrees = donnees.get("data") if isinstance(donnees, dict) else donnees
        return [item for item in (entrees or []) if isinstance(item, dict)]


def _detail_erreur(reponse: httpx.Response) -> str:
    """Message du serveur, ramene a une ligne lisible."""
    try:
        charge = reponse.json()
    except ValueError:
        return reponse.text[:160]
    erreur = charge.get("error") if isinstance(charge, dict) else None
    if isinstance(erreur, dict):
        return str(erreur.get("message") or erreur)[:160]
    return str(erreur or charge)[:160]


def _extraire_texte(donnees: Any) -> str:
    """Contenu du premier choix, sans supposer la forme exacte de la reponse."""
    if not isinstance(donnees, dict):
        return ""
    choix = donnees.get("choices")
    if not isinstance(choix, list) or not choix:
        return ""
    message = choix[0].get("message") if isinstance(choix[0], dict) else None
    if isinstance(message, dict):
        contenu = message.get("content")
        if isinstance(contenu, str):
            return contenu
        # Certains serveurs renvoient une liste de fragments typés.
        if isinstance(contenu, list):
            return "".join(
                fragment.get("text", "")
                for fragment in contenu
                if isinstance(fragment, dict)
            )
    return ""


groq_provider = OpenAICompatibleProvider(AIProviderKind.GROQ, "Groq")
google_provider = OpenAICompatibleProvider(AIProviderKind.GOOGLE, "Google AI Studio")
