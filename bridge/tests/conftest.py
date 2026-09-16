"""Fixtures communes a toute la suite de tests.

Aucune fixture n'ouvre de connexion reseau, ne pilote un vrai terminal
MetaTrader 5, ne parle a Telegram ni a OpenRouter. La base de donnees vit
entierement en memoire et est recreee pour chaque test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config.settings import reload_settings
from app.database.session import (
    dispose_engine,
    init_database,
    reset_engine_for_tests,
    session_scope,
)
from app.main import app as fastapi_app
from app.services.security.auth import pairing_manager
from app.services.trading import announcements as trading_announcements
from app.services.trading.engine import ProcessOutcome, trading_engine
from app.services.trading.paper import PaperTradingService
from app.watcher import execution as watcher_execution

PAPER_BALANCE = 10000.0

# Fixtures qui impliquent un acces reel a la base. Creer le schema coute une
# centaine de millisecondes : on ne le fait que pour les tests concernes, ce
# qui garde la suite complete sous la minute.
DATABASE_FIXTURES = frozenset({"session", "client", "auth_client"})


@pytest.fixture(autouse=True)
async def database(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Moteur remis a zero pour chaque test, base en memoire neuve si besoin.

    Le moteur est systematiquement recree et dispose : deux tests ne partagent
    jamais ni connexion ni donnee.
    """
    reload_settings()
    reset_engine_for_tests()
    pairing_manager.revoke()
    if DATABASE_FIXTURES & set(request.fixturenames):
        await init_database()
    try:
        yield
    finally:
        pairing_manager.revoke()
        await dispose_engine()


@pytest.fixture(autouse=True)
def annonces_muettes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aucun test ne peut publier une annonce de trading pour de vrai.

    Depuis que le cycle de vie des positions s'annonce sur Telegram et sur le
    telephone, une reconciliation de test suffirait a faire partir un message
    dans le vrai canal et une notification sur le vrai appareil. Les deux
    sorties sont donc coupees a la racine pour toute la suite (CDC3 section 61).

    Un test qui veut observer ces annonces remplace lui-meme _pousse et
    _telegram par ses propres espions.
    """

    async def muet_pousse(*args: object, **kwargs: object) -> bool:
        return False

    async def muet_telegram(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(trading_announcements, '_pousse', muet_pousse)
    monkeypatch.setattr(trading_announcements, '_telegram', muet_telegram)


@pytest.fixture(autouse=True)
def watcher_sans_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aucun test ne peut declencher un ordre par le Market Watcher.

    Depuis que le watcher remet ses signaux au moteur de trading, une analyse
    de test qui franchit le seuil de publication appelle ce moteur global --
    dont l'etat depend des tests precedents. Le neutraliser ici garantit la
    regle du CDC3 section 61 : la suite ne fait jamais partir un ordre.

    Un test qui veut observer cette transmission remplace lui-meme
    ``execution.trading_engine`` par son propre espion.
    """

    class MoteurNeutralise:
        async def handle_message(self, *args: object, **kwargs: object) -> ProcessOutcome:
            return ProcessOutcome(
                stage="ignored", detail="Execution neutralisee pendant les tests"
            )

    monkeypatch.setattr(watcher_execution, "trading_engine", MoteurNeutralise())


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Session SQLModel transactionnelle (commit automatique en sortie)."""
    async with session_scope() as db_session:
        yield db_session


@pytest.fixture
async def paper() -> AsyncIterator[PaperTradingService]:
    """Moteur de paper trading isole, sans aucune source de prix externe."""
    service = PaperTradingService(balance=PAPER_BALANCE, price_source=None)
    await service.initialize()
    # Le moteur global doit pointer vers CE simulateur pendant le test.
    trading_engine.attach(None, service)
    trading_engine.mt5_connected = False
    try:
        yield service
    finally:
        await service.shutdown()


@pytest.fixture
async def client(paper: PaperTradingService) -> AsyncIterator[AsyncClient]:
    """Client HTTP branche directement sur l'application ASGI (aucun socket)."""
    assert paper is not None
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://bridge.test") as http_client:
        yield http_client


@pytest.fixture
def geometrie_permissive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Desserre la garde de largeur de stop du watcher, pour les tests de chaine.

    Les bougies du simulateur ne dependent que du symbole et de l'horodatage
    ABSOLU (voir ``_fake_engine.generate_candles``). Selon l'heure a laquelle
    la suite tourne, le stop calcule tient dans ``MAX_STOP_ATR`` ou non : tout
    test qui a besoin qu'un signal EXISTE devient donc vert le matin et rouge
    l'apres-midi, sans qu'une ligne de code ait bouge.

    Constate le 16/09/2026 vers 09h UTC : « Stop trop large (5.4 ATR) » a fait
    tomber sept tests d'un coup, sur des scenarios inchanges depuis des jours.

    A ne PAS utiliser pour eprouver la garde elle-meme : elle a sa propre
    raison d'etre, et ce desserrage la rendrait muette.
    """
    from app.watcher import levels

    monkeypatch.setattr(levels, "MAX_STOP_ATR", 100.0)


@pytest.fixture
async def auth_client(client: AsyncClient) -> AsyncIterator[AsyncClient]:
    """Client deja appaire : l'en-tete Authorization porte un jeton valide."""
    status = await client.get("/api/v1/pairing/status")
    assert status.status_code == 200

    code = pairing_manager.issue()
    response = await client.post(
        "/api/v1/pairing",
        json={
            "code": code.code,
            "deviceId": "pytest-device-0001",
            "name": "Pytest",
            "platform": "test",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
