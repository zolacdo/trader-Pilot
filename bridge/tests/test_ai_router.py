"""Tests du routage et du repli (CDC2 sections 101 a 104).

Trois moteurs distants coexistent -- OpenRouter, Groq, Google AI Studio -- pour
une raison precise : leurs quotas sont independants. Ce qui est verifie ici est
le contrat commun : quand aucun ne repond, l'appelant doit le SAVOIR, avec la
raison, et jamais recevoir une valeur inventee.

Aucun appel reseau : le moteur est un double dont on choisit le comportement
(reponse, panne, JSON invalide).
"""

from __future__ import annotations

import pytest

from app.models.intelligence import AIMode, AIProviderKind, AISettings, AITaskKind
from app.services.ai.base import (
    AICapabilities,
    AIProvider,
    AIProviderError,
    AIProviderStatus,
    AIProviderUnavailable,
    AIResponse,
    extract_json,
)
from app.services.ai.router.router import AIRouter


class FakeProvider(AIProvider):
    """Moteur simule : repond, echoue, ou rend du JSON invalide."""

    def __init__(
        self,
        kind: AIProviderKind = AIProviderKind.OPENROUTER,
        *,
        text: str = '{"direction": "BUY", "confidence": 0.8}',
        error: Exception | None = None,
        latency_ms: int = 40,
    ) -> None:
        self.kind = kind
        self._text = text
        self._error = error
        self._latency = latency_ms
        self.calls = 0

    @property
    def configured(self) -> bool:
        # Le routeur n'interroge que les moteurs configures : sans cette
        # propriete, le double serait ecarte et le test ne mesurerait rien.
        return True

    async def status(self) -> AIProviderStatus:
        return AIProviderStatus(
            kind=self.kind,
            configured=True,
            available=self._error is None,
            model="modele-test",
            capabilities=AICapabilities(json_mode=True),
        )

    async def complete(self, prompt: str, **kwargs) -> AIResponse:
        self.calls += 1
        if self._error is not None:
            raise self._error
        payload = extract_json(self._text)
        return AIResponse(
            provider=self.kind,
            model="modele-test",
            text=self._text,
            latency_ms=self._latency,
            payload=payload,
            valid_json=payload is not None,
        )


def _settings(**changes) -> AISettings:
    base = AISettings(id=1, mode=AIMode.SINGLE, openrouter_enabled=True)
    for key, value in changes.items():
        setattr(base, key, value)
    return base


def _router(remote: FakeProvider | None = None) -> AIRouter:
    return AIRouter(remote or FakeProvider())


# ---------------------------------------------------------------------------
# Choix du moteur
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "task",
    [
        AITaskKind.SIGNAL_PARSE,
        AITaskKind.NEWS_CLASSIFY,
        AITaskKind.MACRO_ANALYSIS,
        AITaskKind.VISION,
    ],
)
def test_toute_tache_part_vers_le_moteur_disponible(task: AITaskKind) -> None:
    """La nature de la tache n'arbitre plus : c'est la disponibilite qui decide."""
    plan = _router().plan(_settings(), task)
    assert plan.order == [AIProviderKind.OPENROUTER]


def test_aucun_moteur_actif_ne_route_nulle_part() -> None:
    """Sans moteur actif, mieux vaut un ordre vide qu'un appel sans destinataire."""
    plan = _router().plan(_settings(openrouter_enabled=False), AITaskKind.SIGNAL_PARSE)
    assert plan.order == []
    assert "Aucun moteur" in plan.reason


def test_la_raison_du_routage_est_toujours_renseignee() -> None:
    """C'est cette phrase qui explique a l'utilisateur ce qui s'est passe."""
    for reglages in (_settings(), _settings(openrouter_enabled=False)):
        plan = _router().plan(reglages, AITaskKind.SIGNAL_PARSE)
        assert plan.reason.strip()


def test_un_moteur_peu_fiable_est_signale_mais_reste_appele() -> None:
    """Ecarter un moteur defaillant priverait d'un quota encore disponible.

    Une mesure de fiabilite basse peut n'etre qu'un mauvais moment. On le dit
    dans la trace, et on l'appelle quand meme -- le repli sur le moteur suivant
    suffit a couvrir une panne reelle.
    """
    router = _router()
    router.record_reliability(AIProviderKind.OPENROUTER, AITaskKind.SIGNAL_PARSE, 0.2, 50)

    plan = router.plan(_settings(), AITaskKind.SIGNAL_PARSE)

    assert plan.order == [AIProviderKind.OPENROUTER]
    assert "fiabilite" in plan.reason


def test_la_latence_est_lissee_et_non_remplacee() -> None:
    """La mesure alimente l'ecran de sante, meme sans arbitrage a rendre."""
    router = _router()
    router.record_latency(AIProviderKind.OPENROUTER, AITaskKind.SIGNAL_PARSE, 1000.0)
    router.record_latency(AIProviderKind.OPENROUTER, AITaskKind.SIGNAL_PARSE, 2000.0)

    # 1000 * 0,7 + 2000 * 0,3 = 1300 : une valeur isolee ne remplace pas tout.
    mesure = router._latency[(AIProviderKind.OPENROUTER, AITaskKind.SIGNAL_PARSE)]
    assert mesure == pytest.approx(1300.0)


# ---------------------------------------------------------------------------
# Echec (CDC2 sections 102 a 104)
# ---------------------------------------------------------------------------

async def test_un_appel_reussi_est_rendu_sans_repli() -> None:
    remote = FakeProvider()
    routed = await AIRouter(remote).complete(
        _settings(), "analyse", task=AITaskKind.SIGNAL_PARSE
    )

    assert routed.provider is AIProviderKind.OPENROUTER
    assert routed.fallback_used is False
    assert remote.calls == 1


async def test_un_moteur_hors_service_leve_une_erreur_explicite() -> None:
    """Aucune valeur inventee : l'appelant doit pouvoir refuser de trader."""
    remote = FakeProvider(error=AIProviderError("429 quota epuise"))

    with pytest.raises(AIProviderUnavailable) as erreur:
        await AIRouter(remote).complete(
            _settings(), "analyse", task=AITaskKind.SIGNAL_PARSE
        )

    assert "429 quota epuise" in str(erreur.value)


async def test_un_json_invalide_est_refuse_et_non_devine() -> None:
    """Une prose sans structure ne doit jamais devenir une decision."""
    remote = FakeProvider(text="je pense que c'est haussier")

    with pytest.raises(AIProviderUnavailable) as erreur:
        await AIRouter(remote).complete(
            _settings(), "analyse", task=AITaskKind.SIGNAL_PARSE
        )

    assert "JSON invalide" in str(erreur.value)


async def test_aucun_moteur_actif_est_refuse() -> None:
    remote = FakeProvider()

    with pytest.raises(AIProviderUnavailable):
        await AIRouter(remote).complete(
            _settings(openrouter_enabled=False), "analyse", task=AITaskKind.SIGNAL_PARSE
        )

    assert remote.calls == 0, "le moteur a ete appele alors qu'il etait desactive"


# ---------------------------------------------------------------------------
# Lecture des sorties de modeles
# ---------------------------------------------------------------------------

def test_json_entoure_de_texte_est_recupere() -> None:
    texte = 'Voici mon analyse :\n```json\n{"direction": "SELL"}\n```\nVoila.'
    assert extract_json(texte) == {"direction": "SELL"}


def test_texte_sans_json_ne_produit_rien() -> None:
    assert extract_json("aucune structure ici") is None
