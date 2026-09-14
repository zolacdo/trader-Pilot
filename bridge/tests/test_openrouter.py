"""OpenRouter : modeles gratuits, coupe-circuit, quotas, sortie IA retypee.

Aucun test n'ouvre de connexion : le client HTTP est remplace par un faux
transport. Regle absolue verifiee ici : un modele payant n'est JAMAIS retenu
automatiquement, et la sortie du modele repasse toujours par un retypage
strict (CDC sections 19, 21, 49 et 73).
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import Direction, OrderType, ParserSource
from app.services.openrouter import client as client_module
from app.services.openrouter.client import (
    CircuitBreaker,
    OpenRouterAuthError,
    OpenRouterClient,
    OpenRouterError,
    OpenRouterRateLimited,
    OpenRouterUnavailable,
    context_length,
    extract_text,
    is_free_model,
    supports_tools,
    supports_vision,
)
from app.services.openrouter.model_selector import (
    NO_FREE_MODEL_MESSAGE,
    FreeModelSelector,
    build_candidate,
    rank_free_models,
)
from app.services.openrouter.service import openrouter_service
from app.services.openrouter.signal_ai import payload_to_signal

FREE_PRICING = {"prompt": "0", "completion": "0", "request": "0", "image": "0"}
PAID_PRICING = {"prompt": "0.0000015", "completion": "0.000002"}


def model(
    model_id: str,
    pricing: dict[str, str] | None = None,
    vision: bool = False,
    tools: bool = False,
    context: int = 32000,
) -> dict[str, Any]:
    return {
        "id": model_id,
        "pricing": pricing if pricing is not None else FREE_PRICING,
        "architecture": {"input_modalities": ["text", "image"] if vision else ["text"]},
        "supported_parameters": ["tools"] if tools else ["temperature"],
        "context_length": context,
    }


# ---------------------------------------------------------------------------
# Faux transport HTTP
# ---------------------------------------------------------------------------

class FakeAsyncClient:
    """Remplace httpx.AsyncClient : rejoue une reponse ou leve une exception."""

    scripted: ClassVar[list[httpx.Response | Exception]] = []
    calls: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def _next(self, method: str, url: str) -> httpx.Response:
        FakeAsyncClient.calls.append((method, url))
        if not FakeAsyncClient.scripted:
            raise AssertionError("Aucune reponse programmee pour cet appel")
        item = FakeAsyncClient.scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        item.request = httpx.Request(method, url)
        return item

    async def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return self._next("GET", url)

    async def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return self._next("POST", url)


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> type[FakeAsyncClient]:
    FakeAsyncClient.scripted = []
    FakeAsyncClient.calls = []
    monkeypatch.setattr(client_module.httpx, "AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


def response(status_code: int, payload: dict[str, Any], **headers: str) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload, headers=headers)


# ---------------------------------------------------------------------------
# is_free_model
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"id": "a/b", "pricing": FREE_PRICING}, True),
        ({"id": "a/b", "pricing": {"prompt": "0", "completion": "0"}}, True),
        ({"id": "a/b", "pricing": {"prompt": "0.0000015", "completion": "0"}}, False),
        ({"id": "a/b", "pricing": PAID_PRICING}, False),
        # Sans prix du tout, seul le suffixe :free fait foi.
        ({"id": "a/b:free"}, True),
        ({"id": "a/b"}, False),
        ({"id": "a/b", "pricing": {}}, False),
        ({"id": "a/b:free", "pricing": {}}, True),
        # Un prix illisible est traite comme payant : dans le doute, on refuse.
        ({"id": "a/b", "pricing": {"prompt": "gratuit"}}, False),
        # Une seule composante payante suffit a disqualifier le modele.
        ({"id": "a/b:free", "pricing": {"prompt": "0", "image": "0.001"}}, False),
    ],
)
def test_is_free_model(payload: dict[str, Any], expected: bool) -> None:
    assert is_free_model(payload) is expected


def test_supports_vision() -> None:
    assert supports_vision(model("a/b", vision=True)) is True
    assert supports_vision(model("a/b", vision=False)) is False
    assert supports_vision({"architecture": {"modality": "text+image->text"}}) is True
    assert supports_vision({"architecture": {"modality": "text->text"}}) is False
    assert supports_vision({}) is False


def test_supports_tools() -> None:
    assert supports_tools(model("a/b", tools=True)) is True
    assert supports_tools(model("a/b", tools=False)) is False
    assert supports_tools({}) is False


def test_context_length() -> None:
    assert context_length({"context_length": 128000}) == 128000
    assert context_length({"context_length": "32000"}) == 32000
    assert context_length({"context_length": None}) == 0
    assert context_length({"context_length": "beaucoup"}) == 0


# ---------------------------------------------------------------------------
# Classement des modeles
# ---------------------------------------------------------------------------

def test_rank_free_models_ne_retient_jamais_un_modele_payant() -> None:
    models = [
        model("openai/gpt-4o", PAID_PRICING, tools=True, context=128000),
        model("anthropic/claude-sonnet", PAID_PRICING, tools=True, context=200000),
        model("deepseek/deepseek-chat:free", tools=True),
    ]
    candidates = rank_free_models(models)
    assert [candidate.model_id for candidate in candidates] == ["deepseek/deepseek-chat:free"]
    assert all(candidate.free for candidate in candidates)


def test_rank_free_models_sans_modele_gratuit() -> None:
    assert rank_free_models([model("openai/gpt-4o", PAID_PRICING)]) == []


def test_rank_free_models_filtre_la_vision() -> None:
    models = [
        model("qwen/qwen-vl:free", vision=True),
        model("qwen/qwen-text:free", vision=False),
    ]
    ids = [candidate.model_id for candidate in rank_free_models(models, need_vision=True)]
    assert ids == ["qwen/qwen-vl:free"]


def test_rank_free_models_ecarte_un_contexte_trop_court() -> None:
    models = [model("tiny/model:free", context=2000), model("big/model:free", context=64000)]
    ids = [candidate.model_id for candidate in rank_free_models(models)]
    assert ids == ["big/model:free"]


def test_rank_free_models_classe_les_meilleurs_en_premier() -> None:
    models = [
        model("inconnu/petit:free", tools=False, context=8000),
        model("nvidia/nemotron:free", tools=True, context=128000),
    ]
    ids = [candidate.model_id for candidate in rank_free_models(models)]
    assert ids[0] == "nvidia/nemotron:free"


def test_build_candidate_expose_les_capacites() -> None:
    candidate = build_candidate(model("nvidia/nemotron:free", tools=True, vision=True))
    payload = candidate.to_dict()
    assert payload["id"] == "nvidia/nemotron:free"
    assert payload["free"] is True
    assert payload["tools"] is True
    assert payload["vision"] is True
    assert payload["context"] == 32000


# ---------------------------------------------------------------------------
# Coupe-circuit
# ---------------------------------------------------------------------------

def test_le_coupe_circuit_s_ouvre_apres_n_echecs() -> None:
    breaker = CircuitBreaker(failure_threshold=4, reset_after_seconds=300.0)
    for _ in range(3):
        breaker.record_failure()
        assert breaker.is_open is False
    breaker.record_failure()
    assert breaker.is_open is True
    assert breaker.seconds_until_reset > 0


def test_le_coupe_circuit_se_referme_apres_le_delai() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_after_seconds=0.0)
    breaker.record_failure()
    assert breaker.is_open is False
    assert breaker.failures == 0


def test_un_succes_remet_le_compteur_a_zero() -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.is_open is False
    assert breaker.seconds_until_reset == 0


# ---------------------------------------------------------------------------
# Client HTTP
# ---------------------------------------------------------------------------

async def test_client_sans_cle_refuse_tout_appel() -> None:
    client = OpenRouterClient(None)
    assert client.configured is False
    with pytest.raises(OpenRouterAuthError):
        await client.list_models()


async def test_list_models_et_cache(fake_http: type[FakeAsyncClient]) -> None:
    fake_http.scripted = [response(200, {"data": [model("a/b:free")]})]
    client = OpenRouterClient("cle-de-test")

    first = await client.list_models()
    second = await client.list_models()  # servi par le cache : aucun appel HTTP

    assert [item["id"] for item in first] == ["a/b:free"]
    assert second == first
    assert len(fake_http.calls) == 1


async def test_free_models_filtre_les_payants(fake_http: type[FakeAsyncClient]) -> None:
    fake_http.scripted = [
        response(200, {"data": [model("a/b:free"), model("openai/gpt-4o", PAID_PRICING)]})
    ]
    client = OpenRouterClient("cle-de-test")
    assert [item["id"] for item in await client.free_models()] == ["a/b:free"]


async def test_quota_atteint_leve_une_erreur_dediee(fake_http: type[FakeAsyncClient]) -> None:
    fake_http.scripted = [
        response(429, {"error": {"message": "rate limit exceeded"}}, **{"retry-after": "60"})
    ]
    client = OpenRouterClient("cle-de-test")

    with pytest.raises(OpenRouterRateLimited) as exc:
        await client.chat("a/b:free", [{"role": "user", "content": "ping"}])

    assert exc.value.retry_after == 60.0
    assert "rate limit exceeded" in str(exc.value)
    assert client.breaker.failures == 1


async def test_cle_refusee(fake_http: type[FakeAsyncClient]) -> None:
    fake_http.scripted = [response(401, {"error": {"message": "invalid key"}})]
    client = OpenRouterClient("mauvaise-cle")
    with pytest.raises(OpenRouterAuthError):
        await client.chat("a/b:free", [{"role": "user", "content": "ping"}])


async def test_modele_introuvable(fake_http: type[FakeAsyncClient]) -> None:
    fake_http.scripted = [response(404, {"error": {"message": "no such model"}})]
    client = OpenRouterClient("cle-de-test")
    with pytest.raises(OpenRouterError):
        await client.chat("a/b:free", [{"role": "user", "content": "ping"}])


async def test_erreur_serveur_compte_comme_un_echec(fake_http: type[FakeAsyncClient]) -> None:
    fake_http.scripted = [response(503, {"error": {"message": "upstream down"}})]
    client = OpenRouterClient("cle-de-test")
    with pytest.raises(OpenRouterUnavailable):
        await client.chat("a/b:free", [{"role": "user", "content": "ping"}])
    assert client.breaker.failures == 1


async def test_panne_reseau_compte_comme_un_echec(fake_http: type[FakeAsyncClient]) -> None:
    fake_http.scripted = [httpx.ConnectError("reseau injoignable")]
    client = OpenRouterClient("cle-de-test")
    with pytest.raises(OpenRouterUnavailable):
        await client.chat("a/b:free", [{"role": "user", "content": "ping"}])
    assert client.breaker.failures == 1


async def test_delai_depasse_compte_comme_un_echec(fake_http: type[FakeAsyncClient]) -> None:
    fake_http.scripted = [httpx.TimeoutException("trop lent")]
    client = OpenRouterClient("cle-de-test")
    with pytest.raises(OpenRouterUnavailable):
        await client.chat("a/b:free", [{"role": "user", "content": "ping"}])


async def test_le_coupe_circuit_ouvert_bloque_sans_appel_http(
    fake_http: type[FakeAsyncClient],
) -> None:
    client = OpenRouterClient("cle-de-test")
    fake_http.scripted = [response(503, {"error": {"message": "down"}}) for _ in range(4)]

    for _ in range(4):
        with pytest.raises(OpenRouterUnavailable):
            await client.chat("a/b:free", [{"role": "user", "content": "ping"}])

    assert client.breaker.is_open is True
    appels = len(fake_http.calls)
    with pytest.raises(OpenRouterUnavailable) as exc:
        await client.chat("a/b:free", [{"role": "user", "content": "ping"}])
    assert "suspendu" in str(exc.value)
    assert len(fake_http.calls) == appels  # aucun appel supplementaire


async def test_reponse_valide_remet_le_coupe_circuit_a_zero(
    fake_http: type[FakeAsyncClient],
) -> None:
    client = OpenRouterClient("cle-de-test")
    client.breaker.record_failure()
    fake_http.scripted = [
        response(200, {"choices": [{"message": {"content": "OK"}}], "model": "a/b:free"})
    ]
    payload = await client.chat("a/b:free", [{"role": "user", "content": "ping"}])
    assert extract_text(payload) == "OK"
    assert client.breaker.failures == 0


def test_extract_text_multimodal() -> None:
    payload = {"choices": [{"message": {"content": [{"text": "bonjour"}, {"text": "monde"}]}}]}
    assert extract_text(payload) == "bonjour\nmonde"
    assert extract_text({"choices": [{"message": {}}]}) == ""
    with pytest.raises(OpenRouterError):
        extract_text({"choices": []})


# ---------------------------------------------------------------------------
# Retypage de la sortie du modele (CDC section 49)
# ---------------------------------------------------------------------------

def test_payload_to_signal_sortie_coherente() -> None:
    signal = payload_to_signal(
        {
            "is_signal": True,
            "symbol": "GOLD",
            "direction": "BUY",
            "order_type": "MARKET",
            "entry_price": 3320.0,
            "stop_loss": 3310.0,
            "take_profits": [3330.0, 3340.0],
        },
        "fake/model:free",
    )
    assert signal.is_signal is True
    assert signal.symbol == "XAUUSD"
    assert signal.direction is Direction.BUY
    assert signal.order_type is OrderType.MARKET
    assert signal.source is ParserSource.AI
    assert signal.ai_model == "fake/model:free"
    # Une lecture par IA ne depasse jamais 0.80 de confiance.
    assert signal.confidence <= 0.80


def test_payload_to_signal_refuse_une_absence_d_intention() -> None:
    signal = payload_to_signal({"is_signal": False}, "fake/model:free")
    assert signal.is_signal is False
    assert "ia_aucune_intention_de_trade" in signal.warnings


def test_l_ia_ne_peut_pas_inventer_un_symbole_inconnu() -> None:
    signal = payload_to_signal(
        {"is_signal": True, "symbol": "MAGIC-COIN", "direction": "BUY", "stop_loss": 1.0},
        "fake/model:free",
    )
    assert signal.is_signal is False
    assert signal.symbol is None
    assert "ia_symbole_non_reconnu" in signal.warnings


def test_l_ia_ne_peut_pas_omettre_la_direction() -> None:
    signal = payload_to_signal(
        {"is_signal": True, "symbol": "XAUUSD", "direction": "peut-etre"}, "fake/model:free"
    )
    assert signal.is_signal is False
    assert "ia_direction_absente" in signal.warnings


def test_un_type_d_ordre_incoherent_est_abandonne() -> None:
    signal = payload_to_signal(
        {
            "is_signal": True,
            "symbol": "XAUUSD",
            "direction": "BUY",
            "order_type": "SELL_LIMIT",
            "entry_price": 3320.0,
        },
        "fake/model:free",
    )
    assert signal.is_signal is True
    assert signal.order_type is None  # jamais corrige a la volee


def test_les_valeurs_illisibles_deviennent_none() -> None:
    signal = payload_to_signal(
        {
            "is_signal": True,
            "symbol": "XAUUSD",
            "direction": "SELL",
            "entry_price": "trois mille",
            "stop_loss": "3350,5",
            "take_profits": [3330.0, "non", -5, None],
        },
        "fake/model:free",
    )
    assert signal.entry_price is None
    assert signal.stop_loss == pytest.approx(3350.5)
    assert signal.take_profits == [3330.0]


def test_une_sortie_ia_sans_stop_loss_a_une_confiance_plus_basse() -> None:
    complet = payload_to_signal(
        {
            "is_signal": True,
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 3320.0,
            "stop_loss": 3310.0,
            "take_profits": [3340.0],
        },
        "fake/model:free",
    )
    partiel = payload_to_signal(
        {"is_signal": True, "symbol": "XAUUSD", "direction": "BUY", "entry_price": 3320.0},
        "fake/model:free",
    )
    assert partiel.confidence < complet.confidence


# ---------------------------------------------------------------------------
# Selecteur de modeles
# ---------------------------------------------------------------------------

async def test_aucun_modele_gratuit_message_explicite_et_aucun_appel_payant(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = OpenRouterClient("cle-de-test")

    async def only_paid(force_refresh: bool = False) -> list[dict[str, Any]]:
        return [model("openai/gpt-4o", PAID_PRICING, tools=True)]

    async def never_called(*args: object, **kwargs: object) -> dict[str, Any]:
        raise AssertionError("Aucun appel ne doit partir vers un modele payant")

    monkeypatch.setattr(client, "list_models", only_paid)
    monkeypatch.setattr(client, "chat", never_called)

    state = await FreeModelSelector(client, session).refresh(run_tests=True)

    assert state.text_model is None
    assert state.text_model_ok is False
    assert state.last_error == NO_FREE_MODEL_MESSAGE
    assert state.free_models == []


async def test_le_selecteur_choisit_un_modele_gratuit(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = OpenRouterClient("cle-de-test")
    catalogue = [
        model("openai/gpt-4o", PAID_PRICING, tools=True, context=128000),
        model("nvidia/nemotron:free", tools=True, context=128000),
        model("qwen/qwen-vl:free", vision=True, context=64000),
    ]

    async def list_models(force_refresh: bool = False) -> list[dict[str, Any]]:
        return catalogue

    monkeypatch.setattr(client, "list_models", list_models)

    state = await FreeModelSelector(client, session).refresh(run_tests=False)

    assert state.text_model == "nvidia/nemotron:free"
    assert state.vision_model == "qwen/qwen-vl:free"
    assert state.text_model_ok is True
    assert all(entry["free"] for entry in state.free_models)
    assert "openai/gpt-4o" not in {entry["id"] for entry in state.free_models}


async def test_un_modele_prefere_payant_est_ignore(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = OpenRouterClient("cle-de-test")

    async def list_models(force_refresh: bool = False) -> list[dict[str, Any]]:
        return [model("openai/gpt-4o", PAID_PRICING), model("deepseek/chat:free", tools=True)]

    monkeypatch.setattr(client, "list_models", list_models)

    state = await FreeModelSelector(client, session).refresh(
        preferred_text="openai/gpt-4o", run_tests=False
    )
    assert state.text_model == "deepseek/chat:free"


async def test_le_mode_manuel_verifie_que_le_choix_reste_gratuit(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = OpenRouterClient("cle-de-test")

    async def list_models(force_refresh: bool = False) -> list[dict[str, Any]]:
        return [model("deepseek/chat:free"), model("openai/gpt-4o", PAID_PRICING)]

    monkeypatch.setattr(client, "list_models", list_models)
    selector = FreeModelSelector(client, session)

    await selector.set_manual("openai/gpt-4o", None)
    state = await selector.refresh(run_tests=False)
    assert state.text_model_ok is False

    await selector.set_manual("deepseek/chat:free", None)
    state = await selector.refresh(run_tests=False)
    assert state.text_model_ok is True


async def test_liste_de_modeles_indisponible(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = OpenRouterClient("cle-de-test")

    async def boom(force_refresh: bool = False) -> list[dict[str, Any]]:
        raise OpenRouterUnavailable("service indisponible")

    monkeypatch.setattr(client, "list_models", boom)

    state = await FreeModelSelector(client, session).refresh()
    assert state.text_model_ok is False
    assert state.last_error is not None
    assert "indisponible" in state.last_error


async def test_test_model_signale_une_reponse_vide(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = OpenRouterClient("cle-de-test")

    async def empty_chat(*args: object, **kwargs: object) -> dict[str, Any]:
        return {"choices": [{"message": {"content": ""}}]}

    monkeypatch.setattr(client, "chat", empty_chat)
    ok, latency, error = await FreeModelSelector(client, session).test_model("a/b:free")
    assert ok is False
    assert error == "Reponse vide"
    assert latency is not None


async def test_test_model_remonte_l_erreur_openrouter(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = OpenRouterClient("cle-de-test")

    async def failing_chat(*args: object, **kwargs: object) -> dict[str, Any]:
        raise OpenRouterRateLimited("quota atteint")

    monkeypatch.setattr(client, "chat", failing_chat)
    ok, _, error = await FreeModelSelector(client, session).test_model("a/b:free")
    assert ok is False
    assert error is not None and "quota" in error


# ---------------------------------------------------------------------------
# Facade de service
# ---------------------------------------------------------------------------

async def test_le_service_non_configure_ne_tente_aucun_appel(session: AsyncSession) -> None:
    assert openrouter_service.configured is False
    signal, error = await openrouter_service.parse_signal(session, "GOLD BUY 3320")
    assert signal is None
    assert error is not None
    assert "cle OpenRouter" in error


async def test_statut_du_service_sans_cle(session: AsyncSession) -> None:
    status = await openrouter_service.status(session)
    assert status["configured"] is False
    assert status["state"] == "NOT_CONFIGURED"
    assert status["textModel"] is None
    assert status["circuitOpen"] is False
