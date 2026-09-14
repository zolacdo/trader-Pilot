"""Correctifs du routage IA constates a l'usage.

Deux des trois defauts d'origine portaient sur le moteur local, qui a ete
retire. Le troisieme reste entier et reste le plus grave : la synchronisation
des modeles n'etait appelee par personne, donc le fournisseur gardait son
modele a ``None`` a vie, se declarait indisponible, et TOUTE la couche
intelligente restait muette alors qu'un modele gratuit etait bien selectionne.

S'y ajoute la nouvelle regle de confrontation : ce qui distingue deux avis,
c'est desormais le MODELE interroge, plus le fournisseur.
"""

from __future__ import annotations

from typing import Any

from app.models.enums import Direction
from app.models.intelligence import (
    AIMode,
    AIProviderKind,
    AISettings,
    AITaskKind,
    ConsensusOutcome,
)
from app.services.ai.base import AIResponse
from app.services.ai.ensemble.service import AIEnsembleService


def _reglages(**changes: Any) -> AISettings:
    base = AISettings(mode=AIMode.SINGLE, openrouter_enabled=True)
    for name, value in changes.items():
        setattr(base, name, value)
    return base


# ---------------------------------------------------------------------------
# Synchronisation des modeles : le defaut le plus couteux
# ---------------------------------------------------------------------------

def test_la_direction_reste_typee() -> None:
    """Garde-fou : le routeur ne doit jamais rendre une direction en texte."""
    assert Direction.BUY.value == "BUY"


async def test_le_moteur_openrouter_recoit_ses_modeles(session, monkeypatch) -> None:
    """Constat : la synchronisation des modeles n'etait appelee par personne.

    Le fournisseur gardait donc son modele a None a vie, se declarait
    indisponible, et le routeur l'ecartait de toute decision. Consensus,
    ensemble et revue d'opportunite restaient muets alors qu'un modele gratuit
    etait bel et bien selectionne.
    """
    from app.services.ai.service import ai_service
    from app.services.openrouter import service as openrouter_module

    monkeypatch.setattr(
        type(openrouter_module.openrouter_service),
        "configured",
        property(lambda self: True),
    )

    async def modele_texte(_session):
        return "fournisseur/modele-gratuit:free"

    async def modele_vision(_session):
        return "fournisseur/modele-vision:free"

    monkeypatch.setattr(
        openrouter_module.openrouter_service, "active_text_model", modele_texte
    )
    monkeypatch.setattr(
        openrouter_module.openrouter_service, "active_vision_model", modele_vision
    )

    await ai_service.configure(session)

    etat = await ai_service._remote.status()
    assert etat.model == "fournisseur/modele-gratuit:free"
    assert etat.vision_model == "fournisseur/modele-vision:free"


async def test_une_selection_indisponible_ne_casse_pas_la_configuration(
    session, monkeypatch
) -> None:
    """Une panne de selection ne doit pas empecher de charger les reglages."""
    from app.services.ai.service import ai_service
    from app.services.openrouter import service as openrouter_module

    monkeypatch.setattr(
        type(openrouter_module.openrouter_service),
        "configured",
        property(lambda self: True),
    )

    async def en_panne(_session):
        raise RuntimeError("OpenRouter injoignable")

    monkeypatch.setattr(openrouter_module.openrouter_service, "active_text_model", en_panne)

    reglages = await ai_service.configure(session)
    assert reglages is not None


# ---------------------------------------------------------------------------
# La confrontation oppose deux MODELES
# ---------------------------------------------------------------------------

class _ProviderEspion:
    """Note quel modele lui est demande a chaque appel."""

    def __init__(self) -> None:
        self.modeles: list[str | None] = []

    async def complete_json(self, prompt: str, *, model: str | None = None, **_: Any):
        self.modeles.append(model)
        return AIResponse(
            provider=AIProviderKind.OPENROUTER,
            model=model or "modele-par-defaut",
            text='{"direction": "BUY", "confidence": 0.8}',
            latency_ms=30,
            payload={"direction": "BUY", "confidence": 0.8},
            valid_json=True,
        )


class _RouteurEspion:
    def __init__(self, provider: _ProviderEspion) -> None:
        self._provider = provider

    def provider(self, _kind: AIProviderKind) -> _ProviderEspion:
        return self._provider

    def available_kinds(self, settings) -> list[AIProviderKind]:
        """Un seul moteur joignable : OpenRouter, s'il est actif."""
        return [AIProviderKind.OPENROUTER] if settings.openrouter_enabled else []


async def test_le_mode_ensemble_interroge_deux_modeles() -> None:
    """Le second avis vient d'un autre MODELE, pas d'un autre fournisseur."""
    espion = _ProviderEspion()
    service = AIEnsembleService(_RouteurEspion(espion))  # type: ignore[arg-type]

    await service.analyse(
        _reglages(mode=AIMode.ENSEMBLE, ensemble_secondary_model="autre/modele:free"),
        "analyse",
        task=AITaskKind.OPPORTUNITY_REVIEW,
    )

    assert espion.modeles == [None, "autre/modele:free"], (
        f"modeles interroges : {espion.modeles}"
    )


async def test_le_mode_simple_n_interroge_qu_un_modele() -> None:
    espion = _ProviderEspion()
    service = AIEnsembleService(_RouteurEspion(espion))  # type: ignore[arg-type]

    await service.analyse(
        _reglages(mode=AIMode.SINGLE, ensemble_secondary_model="autre/modele:free"),
        "analyse",
        task=AITaskKind.OPPORTUNITY_REVIEW,
    )

    assert espion.modeles == [None]


async def test_sans_second_modele_l_ensemble_ne_fait_pas_semblant() -> None:
    """Un seul avis ne vaut pas un accord, et le resultat doit le dire.

    Renvoyer CONSENSUS sur une opinion unique donnerait a un avis isole
    l'autorite d'une confrontation.
    """
    espion = _ProviderEspion()
    service = AIEnsembleService(_RouteurEspion(espion))  # type: ignore[arg-type]

    resultat = await service.analyse(
        _reglages(mode=AIMode.ENSEMBLE, ensemble_secondary_model=""),
        "analyse",
        task=AITaskKind.OPPORTUNITY_REVIEW,
    )

    assert espion.modeles == [None]
    assert resultat.outcome is ConsensusOutcome.INSUFFICIENT_DATA
    assert resultat.confidence <= 0.6


async def test_openrouter_desactive_ne_declenche_aucun_appel() -> None:
    espion = _ProviderEspion()
    service = AIEnsembleService(_RouteurEspion(espion))  # type: ignore[arg-type]

    resultat = await service.analyse(
        _reglages(openrouter_enabled=False), "analyse", task=AITaskKind.OPPORTUNITY_REVIEW
    )

    assert espion.modeles == []
    assert resultat.outcome is ConsensusOutcome.PROVIDER_UNAVAILABLE
