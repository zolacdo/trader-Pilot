"""Un budget de jetons trop court fait echouer l'IA en silence.

Les modeles recents raisonnent avant d'ecrire, et ``max_tokens`` couvre les
deux depenses. Mesure du 13/09/2026 sur nvidia/nemotron-3-ultra via
OpenRouter, avec le meme prompt de classification :

    400 jetons  -> aucune reponse du tout, la liste des choix revient vide
    2000 jetons -> JSON complet, 96 caracteres

L'echec ne ressemble pas a sa cause : le routeur ecarte le moteur, et
l'utilisateur lit « OpenRouter non connecte » alors que la cle est valide et le
quota intact. C'est ce diagnostic trompeur que le plancher supprime.
"""

from __future__ import annotations

import pytest

from app.services.ai.base import MIN_JSON_MAX_TOKENS, json_token_budget


class TestPlancher:
    @pytest.mark.parametrize("demande", [1, 8, 200, 400, 500, 1999])
    def test_un_budget_trop_court_est_releve(self, demande: int) -> None:
        assert json_token_budget(demande, json_mode=True) == MIN_JSON_MAX_TOKENS

    @pytest.mark.parametrize("demande", [2000, 4000, 8000])
    def test_un_budget_suffisant_est_respecte(self, demande: int) -> None:
        """Le plancher releve ; il ne rabote jamais."""
        assert json_token_budget(demande, json_mode=True) == demande

    @pytest.mark.parametrize("demande", [8, 200, 900])
    def test_hors_json_le_budget_n_est_pas_touche(self, demande: int) -> None:
        """Une reponse en texte libre peut legitimement tenir en peu de jetons."""
        assert json_token_budget(demande, json_mode=False) == demande

    def test_le_plancher_couvre_la_mesure_reelle(self) -> None:
        """400 echouait, 2000 suffisait : le plancher doit etre au-dessus."""
        assert MIN_JSON_MAX_TOKENS >= 2000


class TestAppelsDuDepot:
    """Les appels qui avaient un budget trop court ne doivent pas revenir."""

    def test_la_classification_des_depeches_respecte_le_plancher(self) -> None:
        from app.services.news import relevance

        source = _source(relevance)
        assert "max_tokens=400" not in source
        assert "max_tokens=MIN_JSON_MAX_TOKENS" in source

    def test_la_verification_des_signaux_respecte_le_plancher(self) -> None:
        from app.services.signals import verification

        source = _source(verification)
        assert "max_tokens=200" not in source
        assert "max_tokens=MIN_JSON_MAX_TOKENS" in source

    def test_la_lecture_des_signaux_respecte_le_plancher(self) -> None:
        from app.services.openrouter import signal_ai

        source = _source(signal_ai)
        assert '"max_tokens": 500' not in source
        assert '"max_tokens": MIN_JSON_MAX_TOKENS' in source


def _source(module: object) -> str:
    import inspect

    return inspect.getsource(module)  # type: ignore[arg-type]


class TestPlancherApplique:
    """Le plancher doit agir dans la requete envoyee, pas seulement en theorie."""

    async def test_le_corps_envoye_porte_le_budget_releve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx

        from app.services.ai import openai_compatible

        envoyes: list[dict] = []

        class FausseReponse:
            status_code = 200

            def json(self) -> dict:
                return {
                    "choices": [{"message": {"content": '{"ok": true}'}}],
                    "model": "modele-test",
                }

            @property
            def text(self) -> str:
                return '{"ok": true}'

        class FauxClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def __aenter__(self) -> FauxClient:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, url: str, **kwargs: object) -> FausseReponse:
                envoyes.append(kwargs.get("json") or {})
                return FausseReponse()

        monkeypatch.setattr(httpx, "AsyncClient", FauxClient)

        fournisseur = openai_compatible.groq_provider
        monkeypatch.setattr(
            type(fournisseur), "configured", property(lambda self: True)
        )

        await fournisseur.complete(
            "classe ceci", json_mode=True, max_tokens=200, model="modele-test"
        )

        assert envoyes, "aucune requete n'a ete envoyee"
        assert envoyes[0]["max_tokens"] == MIN_JSON_MAX_TOKENS
