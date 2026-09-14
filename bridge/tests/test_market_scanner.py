"""Scanner de marche : analyse locale, persistance et routes HTTP.

Le scanner ne doit JAMAIS appeler une intelligence artificielle : ces tests
verifient qu'il produit ses chiffres tout seul, a partir du simulateur MT5.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import Direction
from app.models.intelligence import MarketRegime, Timeframe, TrendState
from app.repositories import market_repo
from app.services.market_data.engine import MarketDataEngine
from app.services.market_data.provider import reset_market_engine
from app.services.market_data.watchlist import WatchlistService
from app.services.market_scanner.runner import run_scan, symbol_detail
from app.services.market_scanner.scanner import MarketScanner, trading_session
from app.services.mt5.fake_service import FakeMetaTraderService
from app.services.technical_analysis.multi_timeframe import SCALPING_PROFILE
from tests.test_technical_analysis import BASE


async def build_engine() -> MarketDataEngine:
    service = FakeMetaTraderService()
    await service.initialize()
    return MarketDataEngine(service)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def test_session_de_marche_depend_de_l_heure_utc() -> None:
    assert trading_session(BASE.replace(hour=3)) == "ASIA"
    assert trading_session(BASE.replace(hour=9)) == "LONDON"
    assert trading_session(BASE.replace(hour=14)) == "OVERLAP"
    assert trading_session(BASE.replace(hour=18)) == "NEWYORK"
    assert trading_session(BASE.replace(hour=23)) == "ASIA"


async def test_scan_symbol_produit_toutes_les_mesures() -> None:
    engine = await build_engine()
    result = await MarketScanner(engine).scan_symbol("XAUUSD", "XAUUSD", scan_priority=8)

    assert result.error is None
    assert result.usable is True
    assert result.price is not None and result.price > 0
    assert result.atr is not None and result.atr > 0
    assert result.spread_points == 20
    assert result.structure
    assert result.regime in set(MarketRegime)
    assert result.trend in set(TrendState)
    assert 0.0 <= result.setup_potential <= 1.0
    assert 0.0 <= result.priority <= 1.0
    assert result.scan_priority == 8
    assert result.view is not None
    assert result.reasons

    features = result.features
    for key in ("trendD1", "trendH4", "trendH1", "structure", "regime", "session", "atr"):
        assert key in features


async def test_scan_symbol_inconnu_est_signale_sans_exception() -> None:
    engine = await build_engine()
    result = await MarketScanner(engine).scan_symbol("SPX500", "SPX500")
    assert result.usable is False
    assert result.error is not None
    assert "insuffisant" in result.error.lower()
    assert result.setup_potential == 0.0


async def test_scan_symbol_respecte_le_profil_de_strategie() -> None:
    engine = await build_engine()
    result = await MarketScanner(engine, profile=SCALPING_PROFILE).scan_symbol("EURUSD", "EURUSD")
    assert result.view is not None
    assert result.view.profile == "scalping"
    assert set(result.view.states()) == {"H1", "M15", "M5", "M1"}


async def test_direction_de_setup_suit_le_biais() -> None:
    engine = await build_engine()
    result = await MarketScanner(engine).scan_symbol("BTCUSD", "BTCUSD")
    if result.trend is TrendState.BULLISH:
        assert result.setup_direction is Direction.BUY
    elif result.trend is TrendState.BEARISH:
        assert result.setup_direction is Direction.SELL
    else:
        assert result.setup_direction is None
        assert result.risk_reward is None


async def test_scan_many_trie_par_priorite() -> None:
    engine = await build_engine()
    results = await MarketScanner(engine).scan_many(
        [("XAUUSD", "XAUUSD", 5), ("EURUSD", "EURUSD", 5), ("BTCUSD", "BTCUSD", 10)]
    )
    assert len(results) == 3
    priorites = [item.priority for item in results]
    assert priorites == sorted(priorites, reverse=True)


async def test_le_scan_est_deterministe() -> None:
    engine = await build_engine()
    scanner = MarketScanner(engine)
    premier = await scanner.scan_symbol("EURUSD", "EURUSD")
    second = await scanner.scan_symbol("EURUSD", "EURUSD")
    assert premier.structure == second.structure
    assert premier.regime is second.regime
    assert premier.setup_potential == second.setup_potential


# ---------------------------------------------------------------------------
# Passage complet sur la watchlist
# ---------------------------------------------------------------------------

async def test_run_scan_sans_watchlist(session: AsyncSession) -> None:
    engine = await build_engine()
    assert await run_scan(session, engine) == []


async def test_run_scan_ecrit_snapshots_et_regimes(session: AsyncSession) -> None:
    engine = await build_engine()
    watchlist = WatchlistService(engine)
    await watchlist.add(session, "XAUUSD", scan_priority=9)
    await watchlist.add(session, "EURUSD", scan_priority=4)

    results = await run_scan(session, engine)
    assert {item.symbol for item in results} == {"XAUUSD", "EURUSD"}

    snapshots = await market_repo.latest_snapshots(session)
    assert {snapshot.symbol for snapshot in snapshots} == {"XAUUSD", "EURUSD"}
    for snapshot in snapshots:
        assert snapshot.features
        assert snapshot.technical_score is not None

    regimes = await market_repo.list_regimes(session, "XAUUSD")
    assert len(regimes) == 1
    assert regimes[0].timeframe is Timeframe.H1

    items = await market_repo.list_watchlist(session)
    assert all(item.last_scanned_at is not None for item in items)

    # Deuxieme passage : un snapshot de plus, mais pas de regime en double.
    await run_scan(session, engine)
    assert len(await market_repo.list_snapshots(session, "XAUUSD")) == 2
    assert len(await market_repo.list_regimes(session, "XAUUSD")) == 1


async def test_run_scan_sans_persistance(session: AsyncSession) -> None:
    engine = await build_engine()
    await WatchlistService(engine).add(session, "XAUUSD")
    results = await run_scan(session, engine, persist=False)
    assert results
    assert await market_repo.latest_snapshots(session) == []


async def test_run_scan_ignore_les_instruments_desactives(session: AsyncSession) -> None:
    engine = await build_engine()
    watchlist = WatchlistService(engine)
    item, _ = await watchlist.add(session, "XAUUSD")
    assert item is not None
    await market_repo.update_watchlist_item(session, item, {"enabled": False})
    assert await run_scan(session, engine) == []


async def test_purge_des_snapshots(session: AsyncSession) -> None:
    engine = await build_engine()
    await WatchlistService(engine).add(session, "XAUUSD")
    await run_scan(session, engine)
    await run_scan(session, engine)
    await run_scan(session, engine)
    assert await market_repo.purge_snapshots(session, keep_last=1) == 2
    assert len(await market_repo.list_snapshots(session, "XAUUSD")) == 1


async def test_symbol_detail_complet(session: AsyncSession) -> None:
    engine = await build_engine()
    detail = await symbol_detail(session, "GOLD", engine)
    assert detail is not None
    assert detail["symbol"] == "XAUUSD"
    assert detail["brokerSymbol"] == "XAUUSD"
    assert detail["marketState"]["status"] == "OPEN"
    assert detail["metadata"]["digits"] == 2
    assert detail["scan"]["regime"]
    assert set(detail["timeframes"]) >= {"D1", "H4", "H1", "M15"}
    assert detail["scan"]["multiTimeframe"]["states"]


async def test_symbol_detail_instrument_absent(session: AsyncSession) -> None:
    engine = await build_engine()
    assert await symbol_detail(session, "SPX500", engine) is None


# ---------------------------------------------------------------------------
# Routes HTTP
# ---------------------------------------------------------------------------

async def test_routes_market_exigent_un_appairage(client: AsyncClient) -> None:
    for url in ("/api/v1/market/watchlist", "/api/v1/market/symbols", "/api/v1/market/XAUUSD"):
        response = await client.get(url)
        assert response.status_code == 401, url


async def test_route_symboles_disponibles(auth_client: AsyncClient) -> None:
    reset_market_engine()
    response = await auth_client.get("/api/v1/market/symbols")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["brokerSymbolCount"] > 0
    canoniques = {item["canonical"] for item in payload["instruments"]}
    assert "XAUUSD" in canoniques
    assert any(item["canonical"] == "XAUUSD" for item in payload["suggested"])


async def test_route_symboles_recherche(auth_client: AsyncClient) -> None:
    reset_market_engine()
    response = await auth_client.get("/api/v1/market/symbols", params={"search": "GOLD"})
    assert response.status_code == 200
    recherche = response.json()["search"]
    assert recherche["symbol"] == "XAUUSD"
    assert recherche["available"] is True

    response = await auth_client.get("/api/v1/market/symbols", params={"search": "SPX500"})
    recherche = response.json()["search"]
    assert recherche["available"] is False
    assert "introuvable" in recherche["message"]


async def test_cycle_complet_de_watchlist(auth_client: AsyncClient) -> None:
    reset_market_engine()
    vide = await auth_client.get("/api/v1/market/watchlist")
    assert vide.json() == {"count": 0, "items": []}

    cree = await auth_client.post(
        "/api/v1/market/watchlist", json={"symbol": "GOLD", "scanPriority": 9}
    )
    assert cree.status_code == 201, cree.text
    item = cree.json()
    assert item["symbol"] == "XAUUSD"
    assert item["brokerSymbol"] == "XAUUSD"
    assert item["available"] is True
    assert item["scanPriority"] == 9

    modifie = await auth_client.patch(
        "/api/v1/market/watchlist/XAUUSD", json={"scanPriority": 3, "notifyNews": False}
    )
    assert modifie.status_code == 200
    assert modifie.json()["scanPriority"] == 3
    assert modifie.json()["notifyNews"] is False

    liste = await auth_client.get("/api/v1/market/watchlist", params={"enabledOnly": True})
    assert liste.json()["count"] == 1

    supprime = await auth_client.delete("/api/v1/market/watchlist/XAUUSD")
    assert supprime.status_code == 200
    assert supprime.json()["removed"] is True
    assert (await auth_client.delete("/api/v1/market/watchlist/XAUUSD")).status_code == 404


async def test_ajout_d_un_instrument_absent_est_refuse(auth_client: AsyncClient) -> None:
    reset_market_engine()
    response = await auth_client.post("/api/v1/market/watchlist", json={"symbol": "SPX500"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["symbol"] == "SPX500"
    assert "introuvable" in detail["message"]


async def test_modification_d_un_instrument_absent(auth_client: AsyncClient) -> None:
    reset_market_engine()
    manquant = await auth_client.patch(
        "/api/v1/market/watchlist/EURUSD", json={"scanPriority": 2}
    )
    assert manquant.status_code == 404

    await auth_client.post("/api/v1/market/watchlist", json={"symbol": "EURUSD"})
    vide = await auth_client.patch("/api/v1/market/watchlist/EURUSD", json={})
    assert vide.status_code == 400


async def test_route_rafraichissement_de_watchlist(auth_client: AsyncClient) -> None:
    reset_market_engine()
    await auth_client.post("/api/v1/market/watchlist", json={"symbol": "EURUSD"})
    response = await auth_client.post("/api/v1/market/watchlist/refresh")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["available"] == 1


async def test_route_scan(auth_client: AsyncClient) -> None:
    reset_market_engine()
    await auth_client.post("/api/v1/market/watchlist", json={"symbol": "XAUUSD"})

    lance = await auth_client.post("/api/v1/market/scan")
    assert lance.status_code == 200, lance.text
    payload = lance.json()
    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["symbol"] == "XAUUSD"
    assert item["regime"]
    assert item["multiTimeframe"]["states"]

    dernier = await auth_client.get("/api/v1/market/scan")
    assert dernier.status_code == 200
    assert dernier.json()["items"][0]["symbol"] == "XAUUSD"


async def test_route_detail_instrument(auth_client: AsyncClient) -> None:
    reset_market_engine()
    response = await auth_client.get("/api/v1/market/XAUUSD")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["symbol"] == "XAUUSD"
    assert payload["marketState"]["status"] == "OPEN"
    assert payload["scan"]["price"] is not None
    assert payload["timeframes"]["H1"]["timeframe"] == "H1"

    absent = await auth_client.get("/api/v1/market/SPX500")
    assert absent.status_code == 404
    assert "introuvable" in absent.json()["detail"]


async def test_route_bougies(auth_client: AsyncClient) -> None:
    reset_market_engine()
    response = await auth_client.get(
        "/api/v1/market/XAUUSD/candles", params={"timeframe": "M15", "bars": 60}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["timeframe"] == "M15"
    assert payload["count"] == 60
    bougie = payload["candles"][0]
    assert set(bougie) == {"time", "open", "high", "low", "close", "volume"}


@pytest.mark.parametrize("timeframe", ["H7", "toto", "MN1"])
async def test_route_bougies_unite_invalide(auth_client: AsyncClient, timeframe: str) -> None:
    reset_market_engine()
    response = await auth_client.get(
        "/api/v1/market/XAUUSD/candles", params={"timeframe": timeframe}
    )
    assert response.status_code == 400
    assert "Unité de temps inconnue" in response.json()["detail"]


async def test_route_historique_des_regimes(auth_client: AsyncClient) -> None:
    reset_market_engine()
    await auth_client.post("/api/v1/market/watchlist", json={"symbol": "XAUUSD"})
    await auth_client.post("/api/v1/market/scan")
    response = await auth_client.get("/api/v1/market/XAUUSD/regimes")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["timeframe"] == "H1"
