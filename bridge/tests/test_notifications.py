"""Notifications TradePilot : service, transport FCM, routes, rapports.

Aucun test n'ouvre de connexion reseau : Firebase est entierement simule en
remplacant la fabrique de clients httpx du module ``fcm``. La base vit en
memoire, comme pour le reste de la suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config.logging_config import redact
from app.models.enums import Direction, PositionState
from app.models.intelligence import (
    AIConsensusRecord,
    DecisionRecord,
    DecisionSource,
    EconomicEvent,
    NewsImpact,
    NotificationCategory,
    NotificationPriority,
)
from app.models.trading import TradeRecord
from app.repositories import notification_repo
from app.services.events import EventType, event_bus
from app.services.notifications import fcm, reports, templates
from app.services.notifications.fcm import FcmSendResult, FcmTransport
from app.services.notifications.movement import detect_movements, evaluate_market_movement
from app.services.notifications.service import NotificationService, notification_service

PREFIX = "/api/v1"
ACCESS_TOKEN = "ya29.jeton-de-test-tres-secret"
PUSH_TOKEN = "fcm-token-appareil-pytest"


# ---------------------------------------------------------------------------
# Doublures
# ---------------------------------------------------------------------------

class StubTransport:
    """Transport push simule : il enregistre l'appel et rend un resultat."""

    def __init__(self, result: FcmSendResult | None = None, configured: bool = True) -> None:
        self.configured = configured
        self.result = result if result is not None else FcmSendResult(sent=1)
        self.calls: list[dict[str, Any]] = []

    def status(self) -> dict[str, Any]:
        return {"configured": self.configured, "transport": "stub"}

    async def send(self, tokens: list[str], **kwargs: Any) -> FcmSendResult:
        self.calls.append({"tokens": list(tokens), **kwargs})
        return self.result


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


def fake_client_factory(
    recorder: list[dict[str, Any]],
    *,
    message_status: int = 200,
    message_payload: dict[str, Any] | None = None,
):
    """Remplace httpx.AsyncClient : aucune socket n'est ouverte."""

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        async def post(self, url: str, **kwargs: Any) -> FakeResponse:
            recorder.append({"url": url, **kwargs})
            if "oauth2" in url:
                return FakeResponse(200, {"access_token": ACCESS_TOKEN, "expires_in": 3600})
            return FakeResponse(
                message_status,
                message_payload or {"name": "projects/demo/messages/0:1"},
            )

    return _FakeClient


@pytest.fixture(scope="module")
def service_account() -> dict[str, str]:
    """Compte de service jetable, avec une vraie cle RSA (signature reelle)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return {
        "type": "service_account",
        "project_id": "tradepilot-demo",
        "client_email": "bridge@tradepilot-demo.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    }


@pytest.fixture
def fcm_configure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, service_account: dict[str, str]
) -> FcmTransport:
    import json

    path = tmp_path / "fcm-service-account.json"
    path.write_text(json.dumps(service_account), encoding="utf-8")
    monkeypatch.setenv(fcm.ENV_ENABLED, "true")
    monkeypatch.setenv(fcm.ENV_FILE, str(path))
    monkeypatch.delenv(fcm.ENV_INLINE, raising=False)
    transport = FcmTransport()
    transport.reload()
    return transport


@pytest.fixture
def sans_fcm(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    """Etat par defaut d'une installation neuve : Firebase non configure."""
    monkeypatch.setenv(fcm.ENV_ENABLED, "true")
    monkeypatch.setenv(fcm.ENV_FILE, str(tmp_path / "introuvable.json"))
    monkeypatch.delenv(fcm.ENV_INLINE, raising=False)
    fcm.fcm_transport.reload()
    yield
    fcm.fcm_transport.reload()


# ---------------------------------------------------------------------------
# Service : enregistrement, diffusion, securite
# ---------------------------------------------------------------------------

async def test_la_notification_est_enregistree_diffusee_et_poussee(
    session: AsyncSession,
) -> None:
    service = NotificationService(transport=StubTransport())
    async with event_bus.subscription() as queue:
        event = await service.notify(
            NotificationCategory.TRADE,
            NotificationPriority.HIGH,
            "🟢 ACHAT OUVERT — XAUUSD",
            "XAUUSD · ACHAT · 0.02 lot",
            symbol="XAUUSD",
            session=session,
        )
        published = queue.get_nowait()

    assert event is not None and event.id is not None
    assert event.pushed is True
    assert published["type"] == EventType.NOTIFICATION_CREATED
    assert published["data"]["title"].startswith("🟢")
    assert published["data"]["relevance"]["reason"] == "PUSH"
    # La trace durable existe meme si le telephone est eteint.
    assert await notification_repo.count_events(session) == 1


async def test_aucun_secret_ni_ordre_executable_dans_la_charge_utile(
    session: AsyncSession,
) -> None:
    """CDC2 section 94."""
    service = NotificationService(transport=StubTransport())
    event = await service.notify(
        NotificationCategory.TRADE,
        NotificationPriority.HIGH,
        "🏁 POSITION FERMÉE — EURUSD",
        "Compte 512348811 · résultat +1.72 R",
        data={
            "route": "trade",
            "tradeId": 42,
            "apiKey": "sk-or-v1-000111222333444555",
            "pushToken": PUSH_TOKEN,
            "accountLogin": 512348811,
            "placeOrder": {"symbol": "EURUSD", "volume": 0.5},
            "confirmTrade": True,
        },
        symbol="EURUSD",
        session=session,
    )

    assert event is not None
    data = event.data or {}
    assert data["route"] == "trade"
    assert data["tradeId"] == 42
    for interdit in ("apiKey", "pushToken", "placeOrder", "confirmTrade"):
        assert interdit not in data
    assert data["accountLogin"] == "***8811"
    # Le numero de compte complet ne figure pas non plus dans le texte.
    assert "512348811" not in event.body
    assert "***8811" in event.body


async def test_la_notification_est_conservee_meme_sans_transport(
    session: AsyncSession,
) -> None:
    service = NotificationService(transport=StubTransport(configured=False))
    event = await service.notify(
        NotificationCategory.RISK,
        NotificationPriority.CRITICAL,
        "⚠️ LIMITE DE RISQUE",
        "Trading automatique suspendu.",
        session=session,
    )
    assert event is not None
    assert event.pushed is False
    assert event.push_error == "PUSH_TRANSPORT_UNAVAILABLE"
    assert service.transport.calls == []


# ---------------------------------------------------------------------------
# Transport FCM (API HTTP v1)
# ---------------------------------------------------------------------------

async def test_envoi_fcm_complet_jwt_puis_message(
    monkeypatch: pytest.MonkeyPatch, fcm_configure: FcmTransport
) -> None:
    recorder: list[dict[str, Any]] = []
    monkeypatch.setattr(fcm.httpx, "AsyncClient", fake_client_factory(recorder))

    result = await fcm_configure.send(
        [PUSH_TOKEN],
        title="🟢 ACHAT OUVERT — XAUUSD",
        body="Entrée : 3512.40",
        data={"route": "trade", "tradeId": 7},
    )

    assert result.sent == 1 and result.failed == 0 and result.error is None
    assert len(recorder) == 2

    oauth, message = recorder
    assert oauth["url"] == "https://oauth2.googleapis.com/token"
    assert oauth["data"]["grant_type"] == fcm.JWT_GRANT_TYPE
    assert oauth["data"]["assertion"].count(".") == 2  # entete.charge.signature

    assert message["url"].endswith("/v1/projects/tradepilot-demo/messages:send")
    assert message["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    envelope = message["json"]["message"]
    assert envelope["token"] == PUSH_TOKEN
    assert envelope["notification"]["title"].startswith("🟢")
    assert envelope["android"]["priority"] == "HIGH"
    assert envelope["android"]["notification"]["channel_id"] == fcm.ANDROID_CHANNEL_ID
    # Les valeurs de data sont des chaines, comme l'exige l'API HTTP v1.
    assert envelope["data"] == {"route": "trade", "tradeId": "7"}


async def test_le_jeton_dacces_est_reutilise_puis_masque_dans_les_journaux(
    monkeypatch: pytest.MonkeyPatch, fcm_configure: FcmTransport, service_account: dict[str, str]
) -> None:
    recorder: list[dict[str, Any]] = []
    monkeypatch.setattr(fcm.httpx, "AsyncClient", fake_client_factory(recorder))

    for _ in range(3):
        await fcm_configure.send([PUSH_TOKEN], title="Test", body="corps")

    urls = [call["url"] for call in recorder]
    assert urls.count("https://oauth2.googleapis.com/token") == 1

    assert ACCESS_TOKEN not in redact(f"jeton={ACCESS_TOKEN}")
    assert service_account["private_key"] not in redact(service_account["private_key"])


async def test_un_jeton_refuse_est_efface_de_l_appareil(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    registered = await auth_client.post(
        f"{PREFIX}/devices/push-token", json={"token": PUSH_TOKEN}
    )
    assert registered.status_code == 200

    transport = StubTransport(
        FcmSendResult(failed=1, invalid_tokens=[PUSH_TOKEN], error="FCM HTTP 404 (UNREGISTERED)")
    )
    service = NotificationService(transport=transport)
    event = await service.notify(
        NotificationCategory.SYSTEM,
        NotificationPriority.HIGH,
        "🔌 MT5 indisponible",
        "Le terminal ne répond plus.",
    )

    assert event is not None
    assert event.pushed is False
    assert "UNREGISTERED" in (event.push_error or "")
    assert await notification_repo.push_targets(session) == []


async def test_sans_fichier_de_compte_de_service_le_diagnostic_le_dit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv(fcm.ENV_ENABLED, "true")
    monkeypatch.setenv(fcm.ENV_FILE, str(tmp_path / "absent.json"))
    monkeypatch.delenv(fcm.ENV_INLINE, raising=False)
    transport = FcmTransport()
    transport.reload()

    assert transport.configured is False
    status = transport.status()
    assert status["projectId"] is None
    assert "introuvable" in (status["reason"] or "")
    assert "WebSocket" in status["fallback"]

    result = await transport.send([PUSH_TOKEN], title="Test", body="corps")
    assert result.sent == 0 and result.error


async def test_fcm_desactive_explicitement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(fcm.ENV_ENABLED, "false")
    transport = FcmTransport()
    transport.reload()
    assert transport.configured is False
    assert "false" in (transport.unavailable_reason or "")


# ---------------------------------------------------------------------------
# Routes (CDC2 sections 67 et 90)
# ---------------------------------------------------------------------------

async def test_inbox_paginee_et_filtree_par_categorie(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    service = NotificationService(transport=StubTransport())
    await service.notify(
        NotificationCategory.TRADE,
        NotificationPriority.HIGH,
        "🟢 ACHAT OUVERT — XAUUSD",
        "corps",
        symbol="XAUUSD",
        session=session,
    )
    await service.notify(
        NotificationCategory.NEWS,
        NotificationPriority.HIGH,
        "🌍 ACTUALITÉ — IMPACT ÉLEVÉ",
        "La FED laisse ses taux inchangés.",
        session=session,
    )
    await session.commit()

    toutes = await auth_client.get(f"{PREFIX}/notifications")
    assert toutes.status_code == 200
    payload = toutes.json()
    assert payload["total"] == 2
    assert payload["unread"] == 2
    assert len(payload["categories"]) == len(NotificationCategory)

    filtrees = await auth_client.get(f"{PREFIX}/notifications", params={"category": "NEWS"})
    assert filtrees.json()["total"] == 1
    assert filtrees.json()["items"][0]["category"] == "NEWS"

    page = await auth_client.get(f"{PREFIX}/notifications", params={"limit": 1, "offset": 1})
    assert len(page.json()["items"]) == 1


async def test_marquage_lu_unitaire_puis_global(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    service = NotificationService(transport=StubTransport())
    first = await service.notify(
        NotificationCategory.TRADE,
        NotificationPriority.HIGH,
        "🟢 ACHAT OUVERT — XAUUSD",
        "corps",
        symbol="XAUUSD",
        session=session,
    )
    await service.notify(
        NotificationCategory.SIGNAL,
        NotificationPriority.HIGH,
        "📡 SIGNAL TELEGRAM — EURUSD",
        "corps",
        symbol="EURUSD",
        session=session,
    )
    await session.commit()
    assert first is not None

    lu = await auth_client.post(f"{PREFIX}/notifications/{first.id}/read")
    assert lu.status_code == 200
    assert lu.json()["unread"] == 1
    assert lu.json()["notification"]["readAt"] is not None

    tout = await auth_client.post(f"{PREFIX}/notifications/read-all", json={})
    assert tout.status_code == 200
    assert tout.json()["updated"] == 1
    assert tout.json()["unread"] == 0

    absente = await auth_client.post(f"{PREFIX}/notifications/999999/read")
    assert absente.status_code == 404


async def test_preferences_lecture_et_ecriture(auth_client: AsyncClient) -> None:
    lecture = await auth_client.get(f"{PREFIX}/notifications/preferences")
    assert lecture.status_code == 200
    preferences = {item["category"]: item for item in lecture.json()["preferences"]}
    assert len(preferences) == len(NotificationCategory)
    assert preferences["TRADE"]["minimumPriority"] == "HIGH"

    ecriture = await auth_client.put(
        f"{PREFIX}/notifications/preferences",
        json={
            "preferences": [
                {
                    "category": "NEWS",
                    "pushEnabled": False,
                    "minimumPriority": "CRITICAL",
                    "quietHoursStart": "22:30",
                    "quietHoursEnd": "07:00",
                }
            ]
        },
    )
    assert ecriture.status_code == 200
    mises_a_jour = {item["category"]: item for item in ecriture.json()["preferences"]}
    assert mises_a_jour["NEWS"]["pushEnabled"] is False
    assert mises_a_jour["NEWS"]["quietHoursStart"] == "22:30"
    assert mises_a_jour["TRADE"]["pushEnabled"] is True


async def test_heure_de_silence_invalide_refusee(auth_client: AsyncClient) -> None:
    reponse = await auth_client.put(
        f"{PREFIX}/notifications/preferences",
        json={"preferences": [{"category": "NEWS", "quietHoursStart": "25:99"}]},
    )
    assert reponse.status_code == 422


async def test_route_test_et_statut_push_sans_firebase(
    auth_client: AsyncClient, sans_fcm: None
) -> None:
    statut = await auth_client.get(f"{PREFIX}/notifications/push/status")
    assert statut.status_code == 200
    corps = statut.json()
    assert corps["configured"] is False
    assert corps["pushPossible"] is False
    assert "WebSocket" in corps["message"]
    assert corps.get("serviceAccount") is None

    essai = await auth_client.post(f"{PREFIX}/notifications/test")
    assert essai.status_code == 200
    assert essai.json()["sent"] is True
    assert essai.json()["pushed"] is False

    inbox = await auth_client.get(f"{PREFIX}/notifications")
    assert inbox.json()["total"] == 1


async def test_les_routes_exigent_un_appareil_appaire(client: AsyncClient) -> None:
    for methode, chemin in (
        ("get", "/notifications"),
        ("get", "/notifications/preferences"),
        ("get", "/notifications/push/status"),
        ("post", "/notifications/test"),
    ):
        reponse = await getattr(client, methode)(f"{PREFIX}{chemin}")
        assert reponse.status_code == 401, chemin


# ---------------------------------------------------------------------------
# Gabarits (CDC2 sections 52 a 62, verifies par la section 107)
# ---------------------------------------------------------------------------

# Un gabarit par notification listee au CDC2 section 107.
GABARITS: dict[str, Any] = {
    "BUY": templates.position_opened(
        symbol="XAUUSD", direction="BUY", volume=0.02, entry=3512.40, stop_loss=3498.00,
        take_profits=[3528.00], risk_percent=0.5, ai_mode="ENSEMBLE", confidence=0.83,
    ),
    "SELL": templates.position_opened(
        symbol="EURUSD", direction="SELL", volume=0.10, entry=1.0845, digits=4
    ),
    "OPPORTUNITY": templates.opportunity_detected(
        symbol="XAUUSD", direction="BUY", confidence=0.82, technical=0.86,
        historical=0.77, news_risk="LOW", ai_consensus=True,
    ),
    "TELEGRAM": templates.telegram_signal(
        symbol="XAUUSD", direction="BUY", channel_name="Gold Signals",
        verdict="APPROVED", ai_consensus=True, confidence=0.81,
    ),
    "DISAGREEMENT": templates.ai_disagreement(
        symbol="XAUUSD", primary_direction="BUY", secondary_direction="SELL"
    ),
    "TP": templates.take_profit_hit(symbol="XAUUSD", direction="BUY", level=1, profit=34.2),
    "SL": templates.stop_loss_hit(
        symbol="XAUUSD", direction="BUY", result_percent=-0.48, planned_risk_percent=0.5
    ),
    "CLOSED": templates.position_closed(
        symbol="XAUUSD", r_multiple=1.72, profit=86.0, duration_seconds=8100
    ),
    "BREAK_EVEN": templates.break_even_applied(symbol="XAUUSD", new_stop_loss=3512.40),
    "RISK": templates.risk_limit_reached(reason="Limite de perte journali\u00e8re atteinte."),
    "NEWS": templates.high_impact_news(
        headline="La FED laisse entendre des taux \u00e9lev\u00e9s plus longtemps.",
        affected=["USD", "XAUUSD"], source="Reuters",
        published_at=datetime(2026, 3, 4, 14, 30, tzinfo=UTC),
    ),
    "MARKET": templates.market_information(
        headline="R\u00e9sultats trimestriels majeurs publi\u00e9s.", affected=["US100"]
    ),
    "ECONOMIC": templates.economic_event_upcoming(
        title="Non Farm Payrolls", currency="USD",
        scheduled_at=datetime(2026, 3, 6, 13, 30, tzinfo=UTC),
        minutes_before=30, impact=NewsImpact.HIGH,
    ),
    "SYSTEM": templates.system_status(
        service="MT5", online=False, detail="Terminal ferm\u00e9"
    ),
}


@pytest.mark.parametrize("nom", list(GABARITS))
def test_chaque_gabarit_est_lisible_et_sans_secret(nom: str) -> None:
    draft = GABARITS[nom]
    assert draft.title.strip()
    assert draft.body.strip()
    assert len(draft.title) <= 255
    assert "None" not in draft.body
    assert redact(draft.body) == draft.body
    for interdit in ("apiKey", "token", "secret", "password"):
        assert interdit not in (draft.data or {})


def test_les_textes_sont_en_francais_accentue() -> None:
    achat = templates.position_opened(
        symbol="XAUUSD", direction="BUY", volume=0.02, entry=3512.40, risk_percent=0.5
    )
    assert "ACHAT OUVERT" in achat.title
    assert "Entrée" in achat.body
    assert "Risque : 0.5 %" in achat.body

    vente = templates.position_opened(symbol="EURUSD", direction="SELL", volume=0.1)
    assert "VENTE OUVERTE" in vente.title

    desaccord = templates.ai_disagreement(
        symbol="XAUUSD", primary_direction="BUY", secondary_direction="SELL"
    )
    assert "Modèle principal : ACHAT" in desaccord.body
    assert "Second modèle : VENTE" in desaccord.body
    assert "Aucun ordre" in desaccord.body


# ---------------------------------------------------------------------------
# Alertes de mouvement (CDC2 section 65)
# ---------------------------------------------------------------------------

def test_les_six_familles_de_mouvements_sont_reconnues() -> None:
    alertes = detect_movements(
        "XAUUSD",
        change_percent=1.1,
        window_minutes=12,
        volatility_ratio=3.2,
        spread_points=18.0,
        average_spread_points=4.0,
        gap_percent=-0.9,
        candle_range=12.0,
        atr=4.0,
        breakout_level=3520.0,
        breakout_direction="UP",
    )
    genres = {alerte.kind for alerte in alertes}
    assert genres == {
        "ABNORMAL_MOVE",
        "SUDDEN_VOLATILITY",
        "SPREAD_SPIKE",
        "GAP",
        "LARGE_CANDLE",
        "BREAKOUT",
    }
    anormal = next(a for a in alertes if a.kind == "ABNORMAL_MOVE")
    draft = anormal.to_draft()
    assert "MOUVEMENT ANORMAL" in draft.title
    assert "+1.10 % en 12 min" in draft.body
    assert draft.symbol == "XAUUSD"


def test_un_marche_calme_ne_declenche_rien() -> None:
    assert detect_movements(
        "EURUSD",
        change_percent=0.05,
        volatility_ratio=1.1,
        spread_points=1.2,
        average_spread_points=1.0,
        gap_percent=0.01,
        candle_range=1.0,
        atr=4.0,
    ) == []


async def test_le_scanner_peut_publier_ses_alertes(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notification_service, "transport", StubTransport())
    evenements = await evaluate_market_movement(
        "XAUUSD", change_percent=1.4, window_minutes=10, session=session
    )
    assert len(evenements) == 1
    assert evenements[0].category == NotificationCategory.OPPORTUNITY
    assert evenements[0].symbol == "XAUUSD"

    # Rien n'est envoye lorsque l'appelant demande une simple detection.
    assert await evaluate_market_movement("XAUUSD", change_percent=2.0, notify=False) == []


# ---------------------------------------------------------------------------
# Rapports (CDC2 sections 88 et 89)
# ---------------------------------------------------------------------------

async def _remplir_des_trades(session: AsyncSession) -> None:
    jour = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    gagnant = TradeRecord(
        ticket=1,
        symbol="XAUUSD",
        direction=Direction.BUY,
        state=PositionState.CLOSED,
        realized_pnl=120.0,
        r_multiple=1.7,
        opened_at=jour - timedelta(hours=2),
        closed_at=jour,
    )
    perdant = TradeRecord(
        ticket=2,
        symbol="EURUSD",
        direction=Direction.SELL,
        state=PositionState.CLOSED,
        channel_id=77,
        realized_pnl=-40.0,
        r_multiple=-1.0,
        opened_at=jour - timedelta(hours=1),
        closed_at=jour,
    )
    session.add(gagnant)
    session.add(perdant)
    await session.flush()

    decision = DecisionRecord(
        symbol="XAUUSD", source=DecisionSource.AI_GENERATED, trade_id=gagnant.id, executed=True
    )
    session.add(decision)
    await session.flush()
    session.add(
        AIConsensusRecord(
            decision_id=decision.id,
            primary_model="deepseek/deepseek-chat:free",
            secondary_model="nvidia/nemotron",
        )
    )
    session.add(
        EconomicEvent(
            external_id="nfp-2026",
            scheduled_at=jour + timedelta(days=1),
            currency="USD",
            title="Non Farm Payrolls",
            impact=NewsImpact.HIGH,
        )
    )
    await session.flush()


async def test_rapport_quotidien_complet(session: AsyncSession) -> None:
    await _remplir_des_trades(session)
    draft = await reports.build_daily_report(session)

    assert "JOURNAL DU" in draft.title
    assert "Trades : 2" in draft.body
    assert "Gagnants : 1" in draft.body
    assert "Perdants : 1" in draft.body
    assert "Résultat : +80.00" in draft.body
    assert "Ensemble : 1" in draft.body
    assert "Telegram : 1" in draft.body
    assert "Non Farm Payrolls" in draft.body
    assert draft.category == NotificationCategory.DAILY_REPORT


async def test_rapport_hebdomadaire_complet(session: AsyncSession) -> None:
    await _remplir_des_trades(session)
    draft = await reports.build_weekly_report(session)

    assert "BILAN HEBDOMADAIRE" in draft.title
    assert "Taux de réussite : 50 %" in draft.body
    assert "Facteur de profit : 3.00" in draft.body
    assert "Meilleur instrument : XAUUSD" in draft.body
    assert "Instrument le plus faible : EURUSD" in draft.body
    assert "Drawdown max" in draft.body


async def test_rapport_sans_trade_le_dit_franchement(session: AsyncSession) -> None:
    draft = await reports.build_daily_report(session)
    assert "Trades : 0" in draft.body
    assert "Aucune position fermée." in draft.body
    assert "Aucun événement à fort impact annoncé." in draft.body


async def test_envoi_du_rapport_quotidien(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notification_service, "transport", StubTransport())
    await _remplir_des_trades(session)
    event = await reports.send_daily_report(session)

    assert event is not None
    assert event.category == NotificationCategory.DAILY_REPORT
    # Priorite MEDIUM : le rapport s'affiche dans l'application, il ne sonne pas.
    assert event.pushed is False
