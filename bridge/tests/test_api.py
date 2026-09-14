"""API HTTP du Bridge : authentification, lecture, actions protegees.

Le client parle directement a l'application ASGI : aucun socket, aucun port
ouvert. Toutes les routes sensibles doivent exiger un jeton de peripherique
(CDC section 41) et les actions irreversibles une phrase exacte.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.security.auth import pairing_manager
from app.services.trading.paper import PaperTradingService

PREFIX = "/api/v1"

# Routes sensibles : toutes doivent repondre 401 sans jeton.
PROTECTED_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", f"{PREFIX}/status"),
    ("GET", f"{PREFIX}/dashboard"),
    ("GET", f"{PREFIX}/diagnostics"),
    ("GET", f"{PREFIX}/devices"),
    ("GET", f"{PREFIX}/go-live-checklist"),
    ("GET", f"{PREFIX}/signals"),
    ("GET", f"{PREFIX}/signals/pending"),
    ("GET", f"{PREFIX}/risk/settings"),
    ("PATCH", f"{PREFIX}/risk/settings"),
    ("GET", f"{PREFIX}/risk/events"),
    ("GET", f"{PREFIX}/trading/state"),
    ("POST", f"{PREFIX}/trading/pause"),
    ("POST", f"{PREFIX}/trading/resume"),
    ("POST", f"{PREFIX}/trading/execution-mode"),
    ("POST", f"{PREFIX}/trading/live-unlock"),
    ("POST", f"{PREFIX}/trading/live-lock"),
    ("GET", f"{PREFIX}/positions"),
    ("GET", f"{PREFIX}/orders"),
    ("GET", f"{PREFIX}/history"),
    ("GET", f"{PREFIX}/mt5/status"),
    ("GET", f"{PREFIX}/mt5/account"),
    ("POST", f"{PREFIX}/emergency/close-all"),
    ("POST", f"{PREFIX}/emergency/cancel-pending"),
    ("GET", f"{PREFIX}/emergency/info"),
    ("GET", f"{PREFIX}/statistics"),
    ("GET", f"{PREFIX}/statistics/today"),
    ("GET", f"{PREFIX}/journal"),
    ("GET", f"{PREFIX}/journal/audit"),
    ("GET", f"{PREFIX}/onboarding/state"),
    ("POST", f"{PREFIX}/onboarding/complete"),
    ("POST", f"{PREFIX}/signals/parse-test"),
    ("GET", f"{PREFIX}/channels"),
    ("GET", f"{PREFIX}/openrouter/status"),
    ("GET", f"{PREFIX}/symbols/mappings"),
    ("GET", f"{PREFIX}/settings/export"),
)


# ---------------------------------------------------------------------------
# Routes publiques
# ---------------------------------------------------------------------------

async def test_health_accessible_sans_jeton(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "version" in payload
    # La sonde publique ne divulgue aucune donnee de compte.
    assert "balance" not in payload
    assert "account" not in payload


async def test_racine_publique(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "TradePilot Bridge"


async def test_entetes_de_securite(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


async def test_statut_d_appairage_public(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/pairing/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["hasPairedDevice"] is False
    # Le code lui-meme n'est jamais renvoye par l'API.
    assert "code" not in payload


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES, ids=[
    f"{method}:{path}" for method, path in PROTECTED_ROUTES
])
async def test_les_routes_sensibles_exigent_un_jeton(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path, json={})
    assert response.status_code == 401, path
    assert response.headers.get("WWW-Authenticate") == "Bearer"


async def test_un_jeton_invalide_est_refuse(client: AsyncClient) -> None:
    response = await client.get(
        f"{PREFIX}/dashboard", headers={"Authorization": "Bearer jeton-invente"}
    )
    assert response.status_code == 401


async def test_appairage_avec_un_mauvais_code(client: AsyncClient) -> None:
    pairing_manager.issue()
    response = await client.post(
        f"{PREFIX}/pairing",
        json={"code": "MAUV-AIS0", "deviceId": "device-test-0001", "name": "Test"},
    )
    assert response.status_code == 403
    assert "invalide" in response.json()["detail"]


async def test_appairage_sans_code_actif(client: AsyncClient) -> None:
    pairing_manager.revoke()
    response = await client.post(
        f"{PREFIX}/pairing",
        json={"code": "ABCD-EFGH", "deviceId": "device-test-0001", "name": "Test"},
    )
    assert response.status_code == 403


async def test_appairage_accepte_le_code_sans_tiret(client: AsyncClient) -> None:
    """L'application mobile transmet le code compacte, sans le tiret d'affichage.

    Le Bridge affiche XXXX-XXXX pour la lisibilite : refuser la forme compacte
    rendait l'appairage impossible depuis le telephone.
    """
    code = pairing_manager.issue()
    compact = code.code.replace("-", "")
    assert compact != code.code

    response = await client.post(
        f"{PREFIX}/pairing",
        json={"code": compact, "deviceId": "device-sans-tiret", "name": "Telephone"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["token"]


async def test_appairage_accepte_le_code_en_minuscules_et_espace(client: AsyncClient) -> None:
    code = pairing_manager.issue()
    saisie = f" {code.code.lower().replace('-', ' ')} "

    response = await client.post(
        f"{PREFIX}/pairing",
        json={"code": saisie, "deviceId": "device-minuscules", "name": "Telephone"},
    )
    assert response.status_code == 201, response.text


async def test_appairage_avec_le_bon_code_remet_un_jeton(client: AsyncClient) -> None:
    code = pairing_manager.issue()
    response = await client.post(
        f"{PREFIX}/pairing",
        json={"code": code.code, "deviceId": "device-test-0001", "name": "Telephone"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["token"]
    assert payload["deviceId"] == "device-test-0001"

    # Le jeton remis ouvre bien les routes protegees.
    protege = await client.get(
        f"{PREFIX}/trading/state", headers={"Authorization": f"Bearer {payload['token']}"}
    )
    assert protege.status_code == 200

    # Le code est consomme : il ne peut pas resservir.
    rejoue = await client.post(
        f"{PREFIX}/pairing",
        json={"code": code.code, "deviceId": "device-test-0002", "name": "Autre"},
    )
    assert rejoue.status_code == 403


async def test_le_jeton_fonctionne_aussi_en_entete_dediee(auth_client: AsyncClient) -> None:
    token = auth_client.headers["Authorization"].removeprefix("Bearer ")
    response = await auth_client.get(
        f"{PREFIX}/trading/state",
        headers={"Authorization": "", "X-Device-Token": token},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Lecture de l'etat
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        f"{PREFIX}/status",
        f"{PREFIX}/dashboard",
        f"{PREFIX}/diagnostics",
        f"{PREFIX}/risk/settings",
        f"{PREFIX}/signals",
        f"{PREFIX}/signals/pending",
        f"{PREFIX}/trading/state",
        f"{PREFIX}/onboarding/state",
        f"{PREFIX}/positions",
        f"{PREFIX}/orders",
        f"{PREFIX}/history",
        f"{PREFIX}/journal",
        f"{PREFIX}/journal/audit",
        f"{PREFIX}/statistics",
        f"{PREFIX}/statistics/today",
        f"{PREFIX}/risk/events",
        f"{PREFIX}/devices",
        f"{PREFIX}/go-live-checklist",
        f"{PREFIX}/emergency/info",
        f"{PREFIX}/symbols/mappings",
        f"{PREFIX}/settings/export",
        f"{PREFIX}/openrouter/status",
    ],
)
async def test_les_ecrans_de_lecture_repondent(auth_client: AsyncClient, path: str) -> None:
    response = await auth_client.get(path)
    assert response.status_code == 200, f"{path} : {response.text}"


async def test_dashboard_contient_les_blocs_attendus(auth_client: AsyncClient) -> None:
    payload = (await auth_client.get(f"{PREFIX}/dashboard")).json()
    for key in ("bridge", "telegram", "mt5", "account", "trading", "metrics"):
        assert key in payload
    assert payload["openPositions"] == []
    assert payload["pendingOrders"] == []
    assert payload["trading"]["executionMode"] == "PAPER"


async def test_diagnostics_liste_les_verifications(auth_client: AsyncClient) -> None:
    payload = (await auth_client.get(f"{PREFIX}/diagnostics")).json()
    cles = {check["key"] for check in payload["checks"]}
    assert {"bridge", "database", "telegram", "mt5", "openrouter", "websocket"} <= cles
    assert payload["executionMode"] == "PAPER"
    assert isinstance(payload["warnings"], list)


async def test_trading_state_par_defaut(auth_client: AsyncClient) -> None:
    payload = (await auth_client.get(f"{PREFIX}/trading/state")).json()
    assert payload["executionMode"] == "PAPER"
    assert payload["autoTradingEnabled"] is False
    assert payload["liveUnlocked"] is False
    assert payload["paused"] is False


async def test_onboarding_state(auth_client: AsyncClient) -> None:
    payload = (await auth_client.get(f"{PREFIX}/onboarding/state")).json()
    assert payload["completed"] is False
    cles = {step["key"] for step in payload["steps"]}
    assert {"intro", "bridge", "metatrader", "telegram", "risk", "mode"} <= cles


# ---------------------------------------------------------------------------
# Reglages de risque
# ---------------------------------------------------------------------------

async def test_lecture_puis_modification_des_reglages_de_risque(
    auth_client: AsyncClient,
) -> None:
    avant = (await auth_client.get(f"{PREFIX}/risk/settings")).json()
    assert avant["riskPercent"] == 0.5
    assert avant["requireStopLoss"] is True

    response = await auth_client.patch(
        f"{PREFIX}/risk/settings",
        json={"riskPercent": 0.25, "maxPositions": 2, "minConfidence": 0.9},
    )
    assert response.status_code == 200
    apres = response.json()
    assert apres["riskPercent"] == 0.25
    assert apres["maxPositions"] == 2
    assert apres["minConfidence"] == 0.9
    # Les champs non transmis ne bougent pas.
    assert apres["maxLot"] == avant["maxLot"]

    relu = (await auth_client.get(f"{PREFIX}/risk/settings")).json()
    assert relu["riskPercent"] == 0.25


async def test_les_reglages_hors_bornes_sont_refuses(auth_client: AsyncClient) -> None:
    response = await auth_client.patch(f"{PREFIX}/risk/settings", json={"riskPercent": 99})
    assert response.status_code == 422
    assert "Champ invalide" in response.json()["detail"]


async def test_le_deverrouillage_reel_n_est_pas_modifiable_par_les_reglages(
    auth_client: AsyncClient,
) -> None:
    await auth_client.patch(f"{PREFIX}/risk/settings", json={"liveUnlocked": True})
    payload = (await auth_client.get(f"{PREFIX}/risk/settings")).json()
    assert payload["liveUnlocked"] is False


# ---------------------------------------------------------------------------
# Mode d'execution et deverrouillage du reel (CDC section 10)
# ---------------------------------------------------------------------------

async def test_passage_en_reel_refuse_sans_deverrouillage(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        f"{PREFIX}/trading/execution-mode",
        json={"mode": "MT5_LIVE", "confirmation": "JE COMPRENDS LES RISQUES"},
    )
    assert response.status_code == 403
    assert "deverrouille" in response.json()["detail"]

    etat = (await auth_client.get(f"{PREFIX}/trading/state")).json()
    assert etat["executionMode"] == "PAPER"


async def test_deverrouillage_avec_une_mauvaise_phrase(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        f"{PREFIX}/trading/live-unlock",
        json={"confirmation": "je comprends", "acknowledgedRisks": True},
    )
    assert response.status_code == 400
    assert "JE COMPRENDS LES RISQUES" in response.json()["detail"]

    etat = (await auth_client.get(f"{PREFIX}/trading/state")).json()
    assert etat["liveUnlocked"] is False


async def test_deverrouillage_sans_acceptation_des_risques(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        f"{PREFIX}/trading/live-unlock",
        json={"confirmation": "JE COMPRENDS LES RISQUES", "acknowledgedRisks": False},
    )
    assert response.status_code == 400


async def test_deverrouillage_puis_reverrouillage(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        f"{PREFIX}/trading/live-unlock",
        json={"confirmation": "  je comprends les risques  ", "acknowledgedRisks": True},
    )
    assert response.status_code == 200
    assert response.json()["liveUnlocked"] is True

    etat = (await auth_client.get(f"{PREFIX}/trading/state")).json()
    assert etat["liveUnlocked"] is True
    # Deverrouille ne veut pas dire actif.
    assert etat["executionMode"] == "PAPER"

    verrou = await auth_client.post(f"{PREFIX}/trading/live-lock")
    assert verrou.status_code == 200
    assert verrou.json()["liveUnlocked"] is False


async def test_passage_en_reel_sans_la_phrase_exacte(auth_client: AsyncClient) -> None:
    await auth_client.post(
        f"{PREFIX}/trading/live-unlock",
        json={"confirmation": "JE COMPRENDS LES RISQUES", "acknowledgedRisks": True},
    )
    response = await auth_client.post(
        f"{PREFIX}/trading/execution-mode", json={"mode": "MT5_LIVE", "confirmation": "oui"}
    )
    assert response.status_code == 400


async def test_bascule_vers_le_mode_demo(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        f"{PREFIX}/trading/execution-mode", json={"mode": "MT5_DEMO"}
    )
    assert response.status_code == 200
    assert response.json()["executionMode"] == "MT5_DEMO"


# ---------------------------------------------------------------------------
# Arret d'urgence (CDC section 32)
# ---------------------------------------------------------------------------

async def test_fermeture_de_toutes_les_positions_sans_la_phrase_exacte(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        f"{PREFIX}/emergency/close-all", json={"confirmation": "ferme tout"}
    )
    assert response.status_code == 400
    assert "FERMER TOUTES LES POSITIONS" in response.json()["detail"]


async def test_fermeture_de_toutes_les_positions_avec_la_phrase_exacte(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        f"{PREFIX}/emergency/close-all",
        json={"confirmation": "fermer toutes les positions", "suspendAutomation": False},
    )
    assert response.status_code == 200
    assert response.json()["closed"] == 0


async def test_pause_et_reprise(auth_client: AsyncClient) -> None:
    pause = await auth_client.post(
        f"{PREFIX}/trading/pause", json={"reason": "Test", "minutes": 30}
    )
    assert pause.status_code == 200
    assert pause.json()["paused"] is True

    etat = (await auth_client.get(f"{PREFIX}/trading/state")).json()
    assert etat["paused"] is True
    assert etat["pauseReason"] == "Test"

    reprise = await auth_client.post(f"{PREFIX}/trading/resume")
    assert reprise.status_code == 200
    assert reprise.json()["paused"] is False


async def test_activation_du_trading_automatique(auth_client: AsyncClient) -> None:
    response = await auth_client.post(f"{PREFIX}/trading/auto", params={"enabled": True})
    assert response.status_code == 200
    assert response.json()["autoTradingEnabled"] is True


# ---------------------------------------------------------------------------
# Test du parser depuis l'application
# ---------------------------------------------------------------------------

async def test_parse_test_renvoie_l_interpretation_sans_creer_de_signal(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        f"{PREFIX}/signals/parse-test",
        json={"text": "XAUUSD BUY\nENTRY 3320\nSL 3310\nTP1 3330\nTP2 3340", "useAi": False},
    )
    assert response.status_code == 200
    payload = response.json()

    parsed = payload["parsed"]
    assert parsed["isSignal"] is True
    assert parsed["symbol"] == "XAUUSD"
    assert parsed["direction"] == "BUY"
    assert parsed["entryPrice"] == 3320.0
    assert parsed["stopLoss"] == 3310.0
    assert parsed["takeProfits"] == [3330.0, 3340.0]
    assert payload["validation"]["ok"] is True
    assert payload["followUp"] is None
    assert "aucun ordre" in payload["note"]

    # Aucun signal n'a ete enregistre en base.
    signaux = (await auth_client.get(f"{PREFIX}/signals")).json()
    assert signaux["count"] == 0


async def test_parse_test_sur_un_message_de_suivi(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        f"{PREFIX}/signals/parse-test", json={"text": "TP1 HIT MOVE SL BE", "useAi": False}
    )
    payload = response.json()
    assert payload["parsed"]["isSignal"] is False
    assert payload["followUp"]["action"] == "TP_HIT"
    assert payload["followUp"]["alsoBreakEven"] is True


async def test_parse_test_sur_du_bavardage(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        f"{PREFIX}/signals/parse-test",
        json={"text": "GOOD MORNING FAMILY", "useAi": False},
    )
    payload = response.json()
    assert payload["parsed"]["isSignal"] is False
    assert payload["followUp"] is None
    assert payload["validation"]["ok"] is False


async def test_parse_test_refuse_un_texte_vide(auth_client: AsyncClient) -> None:
    response = await auth_client.post(f"{PREFIX}/signals/parse-test", json={"text": ""})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Signaux et positions
# ---------------------------------------------------------------------------

async def test_liste_des_signaux_vide(auth_client: AsyncClient) -> None:
    payload = (await auth_client.get(f"{PREFIX}/signals")).json()
    assert payload == {"count": 0, "offset": 0, "limit": 50, "items": []}


async def test_filtre_de_signaux_inconnu(auth_client: AsyncClient) -> None:
    response = await auth_client.get(f"{PREFIX}/signals", params={"group": "inconnu"})
    assert response.status_code == 400


async def test_detail_d_un_signal_inconnu(auth_client: AsyncClient) -> None:
    assert (await auth_client.get(f"{PREFIX}/signals/99999")).status_code == 404


async def test_positions_et_ordres_vides(
    auth_client: AsyncClient, paper: PaperTradingService
) -> None:
    assert paper is not None
    positions = (await auth_client.get(f"{PREFIX}/positions")).json()
    orders = (await auth_client.get(f"{PREFIX}/orders")).json()
    assert positions["count"] == 0
    assert positions["executionMode"] == "PAPER"
    assert orders["count"] == 0


async def test_details_d_un_symbole_du_simulateur(auth_client: AsyncClient) -> None:
    response = await auth_client.get(f"{PREFIX}/mt5/symbols/XAUUSD")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "XAUUSD"
    assert payload["tick"]["bid"] > 0
    assert payload["spreadPoints"] == 20


async def test_symbole_inconnu(auth_client: AsyncClient) -> None:
    assert (await auth_client.get(f"{PREFIX}/mt5/symbols/INCONNU")).status_code == 404


async def test_recherche_de_symboles(auth_client: AsyncClient) -> None:
    payload = (await auth_client.get(f"{PREFIX}/mt5/symbols", params={"search": "XAU"})).json()
    assert "XAUUSD" in payload["symbols"]


# ---------------------------------------------------------------------------
# Sauvegarde et restauration
# ---------------------------------------------------------------------------

async def test_export_des_reglages_ne_contient_aucun_secret(auth_client: AsyncClient) -> None:
    payload = (await auth_client.get(f"{PREFIX}/settings/export")).json()
    # La note explicative parle de secrets : on inspecte les donnees exportees.
    donnees = str({"risk": payload["risk"], "mappings": payload["symbolMappings"]}).lower()
    for interdit in ("apikey", "api_key", "token", "session", "password", "secret", "masterkey"):
        assert interdit not in donnees, interdit
    assert payload["risk"]["riskPercent"] == 0.5


async def test_import_ne_restaure_jamais_les_interrupteurs_dangereux(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        f"{PREFIX}/settings/import",
        json={
            "payload": {
                "risk": {
                    "riskPercent": 0.75,
                    "autoTradingEnabled": True,
                    "executionMode": "MT5_LIVE",
                    "liveUnlocked": True,
                }
            }
        },
    )
    assert response.status_code == 200

    etat = (await auth_client.get(f"{PREFIX}/trading/state")).json()
    assert etat["autoTradingEnabled"] is False
    assert etat["executionMode"] == "PAPER"
    assert etat["liveUnlocked"] is False
    reglages = (await auth_client.get(f"{PREFIX}/risk/settings")).json()
    assert reglages["riskPercent"] == 0.75
