"""Routes HTTP du Market Watcher et garde-fous de la lecture IA.

Aucun appel reseau : l'IA est desactivee par configuration, et les routes sont
appelees directement sur l'application ASGI.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.core import utcnow
from app.models.enums import Direction
from app.watcher import ai, repository
from app.watcher.config import WatcherConfig, invalidate_cache
from app.watcher.levels import build_levels
from app.watcher.models import WatcherDecision, WatcherSignal, WatcherStatus
from app.watcher.scoring import score_direction
from tests.test_watcher_decision import make_context

BASE = "/api/v1/watcher"


@pytest.fixture(autouse=True)
def _config_propre() -> None:
    """Chaque test repart d'une configuration non memorisee."""
    invalidate_cache()
    ai.clear_cache()


async def _creer_signal(session) -> WatcherSignal:
    signal = WatcherSignal(
        symbol="XAUUSD",
        broker_symbol="XAUUSD",
        direction=Direction.BUY,
        decision=WatcherDecision.BUY,
        status=WatcherStatus.CONFIRMED,
        timeframe="M15",
        entry=3350.0,
        stop_loss=3340.0,
        digits=2,
        take_profit_1=3360.0,
        risk_distance=10.0,
        risk_reward_1=1.0,
        score=74.0,
        confidence=74,
        created_at=utcnow(),
    )
    await repository.add_signal(session, signal)
    return signal


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
class TestRoutes:
    async def test_les_routes_exigent_un_appareil_appaire(self, client: AsyncClient) -> None:
        for chemin in ("/health", "/markets", "/signals", "/performance", "/settings"):
            response = await client.get(f"{BASE}{chemin}")
            assert response.status_code == 401, chemin

    async def test_health_expose_l_etat_du_sous_systeme(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get(f"{BASE}/health")
        assert response.status_code == 200
        payload = response.json()
        assert "loops" in payload["state"]
        assert set(payload["state"]["loops"]) == {
            "analysis",
            "lifecycle",
            "news",
            "maintenance",
        }
        assert payload["telegram"]["resolved"] in (True, False)

    async def test_reglages_lisibles_et_modifiables(self, auth_client: AsyncClient) -> None:
        lecture = await auth_client.get(f"{BASE}/settings")
        assert lecture.status_code == 200
        assert lecture.json()["settings"]["telegramChannel"]

        ecriture = await auth_client.put(
            f"{BASE}/settings", json={"changes": {"minimum_score": 77, "dry_run": True}}
        )
        assert ecriture.status_code == 200
        assert ecriture.json()["settings"]["minimumScore"] == 77.0
        assert ecriture.json()["settings"]["dryRun"] is True

    async def test_reglage_inconnu_renvoie_422(self, auth_client: AsyncClient) -> None:
        response = await auth_client.put(
            f"{BASE}/settings", json={"changes": {"parametre_invente": 1}}
        )
        assert response.status_code == 422
        assert "inconnus" in response.json()["detail"]

    async def test_liste_des_signaux(self, auth_client: AsyncClient, session) -> None:
        await _creer_signal(session)
        response = await auth_client.get(f"{BASE}/signals", params={"days": 365})
        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert response.json()["items"][0]["symbol"] == "XAUUSD"

    async def test_signaux_actifs(self, auth_client: AsyncClient, session) -> None:
        await _creer_signal(session)
        response = await auth_client.get(f"{BASE}/signals/active")
        assert response.status_code == 200
        assert response.json()["count"] == 1

    async def test_detail_d_un_signal_avec_ses_evenements(
        self, auth_client: AsyncClient, session
    ) -> None:
        signal = await _creer_signal(session)
        assert signal.id is not None
        await repository.add_event(session, signal.id, WatcherStatus.CREATED, price=3350.0)
        response = await auth_client.get(f"{BASE}/signals/{signal.id}")
        assert response.status_code == 200
        assert response.json()["signal"]["id"] == signal.id
        assert len(response.json()["events"]) == 1

    async def test_signal_inconnu_renvoie_404(self, auth_client: AsyncClient) -> None:
        assert (await auth_client.get(f"{BASE}/signals/99999")).status_code == 404

    async def test_instrument_sans_analyse_renvoie_404(
        self, auth_client: AsyncClient
    ) -> None:
        assert (await auth_client.get(f"{BASE}/markets/ZZZUSD")).status_code == 404

    async def test_performance_renvoie_un_bilan(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get(f"{BASE}/performance", params={"days": 30})
        assert response.status_code == 200
        assert "summary" in response.json()
        assert response.json()["report"]["overall"]["trades"] == 0

    async def test_performance_separe_la_bande_mesuree_du_reel(
        self, auth_client: AsyncClient, session
    ) -> None:
        """Les deux bandes cote a cote : c'est la comparaison qui decide du seuil.

        Sans elle, la mesure vit en base et personne ne peut la lire pour
        juger si le seuil merite de descendre.
        """
        reel = await _creer_signal(session)
        reel.status = WatcherStatus.SL_HIT
        reel.result_r = -1.0
        fantome = await _creer_signal(session)
        fantome.shadow = True
        fantome.status = WatcherStatus.TP3_HIT
        fantome.result_r = 2.0
        await session.flush()

        payload = (await auth_client.get(f"{BASE}/performance")).json()

        assert payload["report"]["overall"]["trades"] == 1
        assert payload["report"]["overall"]["totalR"] == pytest.approx(-1.0)
        assert payload["shadowBand"]["overall"]["trades"] == 1
        assert payload["shadowBand"]["overall"]["totalR"] == pytest.approx(2.0)

    async def test_cible_de_boucle_inconnue_renvoie_422(
        self, auth_client: AsyncClient
    ) -> None:
        response = await auth_client.post(f"{BASE}/run/inexistante")
        assert response.status_code == 422

    async def test_le_watcher_apparait_dans_la_documentation(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        chemins = response.json()["paths"]
        assert f"{BASE}/health" in chemins
        assert f"{BASE}/signals/active" in chemins


# ---------------------------------------------------------------------------
# Garde-fous de la lecture IA (CDC3 sections 22, 73 et 75)
# ---------------------------------------------------------------------------
class TestGardeFousIA:
    def _materiel(self):
        config = WatcherConfig()
        context = make_context()
        levels = build_levels(context, Direction.BUY, config.minimum_rr)
        card = score_direction(context, Direction.BUY, levels, config)
        return context, levels, card, config

    async def test_ia_desactivee_n_appelle_rien(self) -> None:
        context, levels, card, config = self._materiel()
        config.ai_enabled = False
        reading = await ai.review(context, Direction.BUY, levels, card, config)
        assert reading.available is False
        assert "desactivee" in (reading.reason or "")

    async def test_score_trop_faible_n_appelle_pas_l_ia(self) -> None:
        """Sous le seuil, aucun jeton n'est depense (CDC3 section 73)."""
        context, levels, card, config = self._materiel()
        config.ai_min_score = 999.0
        reading = await ai.review(context, Direction.BUY, levels, card, config)
        assert reading.available is False
        assert "seuil d'appel IA" in (reading.reason or "")

    async def test_une_reponse_tronquee_degrade_sans_casser(self, monkeypatch) -> None:
        """Cas reellement rencontre : un modele s'arrete au milieu du JSON.

        Le budget de jetons etait trop court pour les modeles qui raisonnent
        avant d'ecrire. La lecture doit alors etre declaree indisponible avec un
        motif clair, jamais provoquer d'erreur ni de signal sans commentaire.
        """
        from app.models.intelligence import AIProviderKind
        from app.services.ai.base import AIResponse
        from app.services.ai.router.router import RoutedResponse, RoutingDecision

        tronquee = AIResponse(
            provider=AIProviderKind.GOOGLE,
            model="gemini-flash-latest",
            text='{\n  "bias": "NEUTRAL",\n  "confidence": 55,\n',
            latency_ms=120,
            payload=None,
            valid_json=False,
        )

        async def faux_appel(*args, **kwargs):
            return RoutedResponse(
                response=tronquee,
                provider=AIProviderKind.GOOGLE,
                fallback_used=False,
                routing=RoutingDecision([AIProviderKind.GOOGLE], "test", "SINGLE"),
                attempts=[],
            )

        from app.services.ai.service import ai_service

        monkeypatch.setattr(ai_service, "complete_json", faux_appel)
        context, levels, card, config = self._materiel()
        config.ai_min_score = 0.0
        ai.clear_cache()

        reading = await ai.review(context, Direction.BUY, levels, card, config)
        assert reading.available is False
        assert reading.opinion is None
        assert "JSON" in (reading.reason or "")
        assert reading.comment is None
        assert reading.risks == []

    async def test_une_panne_du_moteur_ne_leve_jamais(self, monkeypatch) -> None:
        """Une IA injoignable n'empeche pas un signal deterministe de sortir."""

        async def casse(*args, **kwargs):
            raise RuntimeError("quota epuise")

        from app.services.ai.service import ai_service

        monkeypatch.setattr(ai_service, "complete_json", casse)
        context, levels, card, config = self._materiel()
        config.ai_min_score = 0.0
        ai.clear_cache()

        reading = await ai.review(context, Direction.BUY, levels, card, config)
        assert reading.available is False
        assert "quota epuise" in (reading.reason or "")

    def test_le_budget_de_jetons_couvre_les_modeles_qui_raisonnent(self) -> None:
        """Mesure sur ce projet : en dessous de ~2000, le JSON revient tronque."""
        assert ai.MAX_TOKENS >= 2000

    def test_le_schema_de_reponse_ne_contient_aucun_prix(self) -> None:
        """L'IA ne peut structurellement pas proposer un niveau (CDC3 section 22)."""
        champs = set(ai.AIOpinion.model_fields)
        for interdit in ("entry", "stop_loss", "take_profit", "price", "sl", "tp"):
            assert interdit not in champs

    def test_le_prompt_transmet_les_niveaux_deja_calcules(self) -> None:
        context, levels, card, _ = self._materiel()
        prompt, payload = ai.build_prompt(context, Direction.BUY, levels, card)
        assert payload["niveaux_deja_calcules"]["entree"] == levels.entry
        assert "ne les modifie pas" in prompt

    def test_une_reponse_hors_schema_est_rejetee(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ai.AIOpinion.model_validate({"bias": "PEUT-ETRE", "confidence": 50})

    def test_une_confiance_hors_bornes_est_rejetee(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ai.AIOpinion.model_validate({"confidence": 150})

    def test_une_reponse_partielle_reste_exploitable(self) -> None:
        """Les champs absents prennent leur valeur neutre, pas une valeur inventee."""
        opinion = ai.AIOpinion.model_validate({"bias": "BULLISH", "confidence": 60})
        assert opinion.recommendation == "WAIT"
        assert opinion.fundamental_impact == "UNKNOWN"
        assert opinion.risks == []
