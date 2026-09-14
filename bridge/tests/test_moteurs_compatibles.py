"""Moteurs distants parlant le dialecte OpenAI : Groq et Google AI Studio.

Pourquoi ils existent : OpenRouter plafonne les modeles gratuits a 50 requetes
par jour sans credit achete. Mesure du 12/09/2026, le plafond etait atteint des
la mi-journee, et la confrontation a deux avis devenait impossible -- le second
modele echouait systematiquement avec « Quota OpenRouter atteint ».

Des quotas INDEPENDANTS rendent le second avis reellement disponible. Ces
tests verrouillent le contrat : aucune cle en clair, un echec qui dit pourquoi,
et un repli d'un moteur a l'autre.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.models.intelligence import AIProviderKind, AISettings, AITaskKind
from app.services.ai.base import AIProviderError, AIProviderUnavailable
from app.services.ai.openai_compatible import (
    DEFAULT_MODELS,
    KNOWN_ENDPOINTS,
    OpenAICompatibleProvider,
    RemoteConfig,
)
from app.services.ai.router.router import AIRouter


def _moteur(**changes: Any) -> OpenAICompatibleProvider:
    fournisseur = OpenAICompatibleProvider(AIProviderKind.GROQ, "Groq")
    base = {
        "enabled": True,
        "base_url": KNOWN_ENDPOINTS[AIProviderKind.GROQ],
        "api_key": "cle-de-test",
        "model": "llama-3.3-70b-versatile",
    }
    base.update(changes)
    fournisseur.configure(RemoteConfig(**base))  # type: ignore[arg-type]
    return fournisseur


def _reponse(contenu: str, statut: int = 200) -> httpx.Response:
    corps: dict[str, Any] = (
        {"choices": [{"message": {"content": contenu}}], "usage": {"total_tokens": 42}}
        if statut < 400
        else {"error": {"message": contenu}}
    )
    return httpx.Response(statut, json=corps)


def _transport(reponse: httpx.Response, vu: list[httpx.Request]) -> Any:
    def gestionnaire(request: httpx.Request) -> httpx.Response:
        vu.append(request)
        return reponse

    return httpx.MockTransport(gestionnaire)


def _brancher(monkeypatch: pytest.MonkeyPatch, reponse: httpx.Response) -> list[httpx.Request]:
    vu: list[httpx.Request] = []
    original = httpx.AsyncClient

    def fabrique(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = _transport(reponse, vu)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fabrique)
    return vu


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def test_un_moteur_sans_cle_n_est_pas_configure() -> None:
    assert _moteur(api_key="").configured is False


def test_un_moteur_desactive_n_est_pas_configure() -> None:
    assert _moteur(enabled=False).configured is False


def test_le_modele_par_defaut_sert_de_repli() -> None:
    """Ne rien choisir ne doit pas rendre le moteur muet."""
    assert _moteur(model="").model == DEFAULT_MODELS[AIProviderKind.GROQ]


async def test_un_moteur_non_configure_refuse_clairement() -> None:
    with pytest.raises(AIProviderUnavailable) as erreur:
        await _moteur(api_key="").complete("bonjour")
    assert "Groq" in str(erreur.value)


# ---------------------------------------------------------------------------
# Appel
# ---------------------------------------------------------------------------

async def test_la_cle_part_en_en_tete_et_jamais_dans_l_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une cle dans l'URL finirait dans les journaux de tous les proxys."""
    vu = _brancher(monkeypatch, _reponse('{"direction": "BUY", "confidence": 0.8}'))

    await _moteur().complete("analyse", json_mode=True)

    requete = vu[0]
    assert requete.headers["authorization"] == "Bearer cle-de-test"
    assert "cle-de-test" not in str(requete.url)


async def test_la_reponse_json_est_lue(monkeypatch: pytest.MonkeyPatch) -> None:
    _brancher(monkeypatch, _reponse('{"direction": "SELL", "confidence": 0.7}'))

    reponse = await _moteur().complete("analyse", json_mode=True)

    assert reponse.valid_json is True
    assert reponse.payload == {"direction": "SELL", "confidence": 0.7}
    assert reponse.provider is AIProviderKind.GROQ
    assert reponse.latency_ms >= 0


async def test_un_modele_impose_prime_sur_le_defaut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C'est ainsi que l'ensemble obtient deux avis distincts."""
    vu = _brancher(monkeypatch, _reponse('{"direction": "BUY"}'))

    await _moteur().complete("analyse", model="autre-modele")

    import json

    assert json.loads(vu[0].content)["model"] == "autre-modele"


@pytest.mark.parametrize(
    ("statut", "extrait"),
    [(429, "quota"), (401, "invalide"), (500, "panne")],
)
async def test_un_refus_dit_pourquoi(
    monkeypatch: pytest.MonkeyPatch, statut: int, extrait: str
) -> None:
    """Un echec muet laisserait croire a un incident reseau passager."""
    _brancher(monkeypatch, _reponse(f"message {extrait}", statut=statut))

    with pytest.raises(AIProviderError) as erreur:
        await _moteur().complete("analyse")

    message = str(erreur.value)
    assert str(statut) in message
    assert extrait in message


async def test_une_prose_sans_json_ne_devient_pas_une_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _brancher(monkeypatch, _reponse("je pense que c'est haussier"))

    reponse = await _moteur().complete("analyse", json_mode=True)

    assert reponse.valid_json is False
    assert reponse.payload is None


# ---------------------------------------------------------------------------
# Routage entre plusieurs moteurs
# ---------------------------------------------------------------------------

class _FauxOpenRouter:
    kind = AIProviderKind.OPENROUTER

    def __init__(self, configure: bool) -> None:
        self._configure = configure

    @property
    def configured(self) -> bool:
        return self._configure


def _reglages(**changes: Any) -> AISettings:
    base = AISettings(openrouter_enabled=True)
    for cle, valeur in changes.items():
        setattr(base, cle, valeur)
    return base


def test_les_moteurs_joignables_sont_listes_dans_l_ordre() -> None:
    routeur = AIRouter(_FauxOpenRouter(True), extras=(_moteur(),))

    ordre = routeur.available_kinds(_reglages())

    assert ordre == [AIProviderKind.OPENROUTER, AIProviderKind.GROQ]


def test_un_moteur_sans_cle_n_est_pas_propose() -> None:
    routeur = AIRouter(_FauxOpenRouter(True), extras=(_moteur(api_key=""),))

    assert routeur.available_kinds(_reglages()) == [AIProviderKind.OPENROUTER]


def test_groq_prend_le_relais_quand_openrouter_est_absent() -> None:
    """Le cas qui motive tout : OpenRouter a sec, un autre quota repond."""
    routeur = AIRouter(_FauxOpenRouter(False), extras=(_moteur(),))

    ordre = routeur.available_kinds(_reglages())

    assert ordre == [AIProviderKind.GROQ]


def test_aucun_moteur_joignable_ne_route_nulle_part() -> None:
    routeur = AIRouter(_FauxOpenRouter(False), extras=(_moteur(api_key=""),))

    plan = routeur.plan(_reglages(), AITaskKind.OPPORTUNITY_REVIEW)

    assert plan.order == []
    assert "Aucun moteur" in plan.reason
