"""Moteur de donnees de marche, cache de bougies et watchlist.

Aucun test ne touche au reseau ni a un terminal MetaTrader reel : tout passe
par ``FakeMetaTraderService``, dont les bougies sont SYNTHETIQUES.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.intelligence import Timeframe
from app.repositories import market_repo
from app.services.market_data.cache import MAX_TTL_SECONDS, MIN_TTL_SECONDS, CandleCache, ttl_for
from app.services.market_data.engine import (
    SUPPORTED_TIMEFRAMES,
    MarketDataEngine,
    parse_timeframe,
)
from app.services.market_data.provider import market_engine, reset_market_engine
from app.services.market_data.watchlist import DEFAULT_WATCHLIST, WatchlistService
from app.services.mt5.fake_service import FakeMetaTraderService
from app.services.mt5.interface import Candle


def sample_candles(count: int = 5) -> list[Candle]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Candle(time=base + timedelta(hours=index), open=1.0, high=2.0, low=0.5, close=1.5)
        for index in range(count)
    ]


async def build_engine() -> MarketDataEngine:
    service = FakeMetaTraderService()
    await service.initialize()
    return MarketDataEngine(service)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def test_ttl_croit_avec_la_taille_de_la_bougie() -> None:
    assert ttl_for(1) == MIN_TTL_SECONDS * 3  # M1 : 30 secondes
    assert ttl_for(1440) == MAX_TTL_SECONDS
    assert ttl_for(0) == MIN_TTL_SECONDS


def test_cache_rend_la_serie_puis_expire() -> None:
    horloge = {"t": 0.0}
    cache = CandleCache(clock=lambda: horloge["t"])
    cache.put("XAUUSD", "H1", sample_candles(10))

    assert cache.get("XAUUSD", "H1", ttl=60.0, minimum=5) is not None
    horloge["t"] = 61.0
    assert cache.get("XAUUSD", "H1", ttl=60.0, minimum=5) is None
    assert len(cache) == 0


def test_cache_refuse_une_serie_trop_courte() -> None:
    cache = CandleCache()
    cache.put("XAUUSD", "H1", sample_candles(3))
    assert cache.get("XAUUSD", "H1", ttl=600.0, minimum=10) is None
    assert cache.get("XAUUSD", "H1", ttl=600.0, minimum=3) is not None


def test_cache_evince_les_plus_anciennes_entrees() -> None:
    cache = CandleCache(max_entries=8)
    for index in range(20):
        cache.put(f"SYM{index}", "H1", sample_candles(2))
    assert len(cache) == 8


def test_cache_invalide_par_symbole_et_globalement() -> None:
    cache = CandleCache()
    cache.put("XAUUSD", "H1", sample_candles(2))
    cache.put("XAUUSD", "M15", sample_candles(2))
    cache.put("EURUSD", "H1", sample_candles(2))
    assert cache.invalidate("XAUUSD") == 2
    assert len(cache) == 1
    assert cache.invalidate() == 1
    stats = cache.stats()
    assert stats["entries"] == 0


# ---------------------------------------------------------------------------
# Moteur
# ---------------------------------------------------------------------------

def test_parse_timeframe() -> None:
    assert parse_timeframe("h1") is Timeframe.H1
    assert parse_timeframe(Timeframe.D1) is Timeframe.D1
    assert parse_timeframe("H7") is None
    assert parse_timeframe(None) is None


@pytest.mark.parametrize("timeframe", SUPPORTED_TIMEFRAMES)
async def test_candles_sur_toutes_les_unites_supportees(timeframe: Timeframe) -> None:
    engine = await build_engine()
    candles = await engine.candles("XAUUSD", timeframe, 60)
    assert candles, f"aucune bougie pour {timeframe.value}"
    assert len(candles) <= 60
    # La serie est triee du plus ancien au plus recent.
    assert candles == sorted(candles, key=lambda item: item.time)


async def test_candles_utilise_le_cache() -> None:
    engine = await build_engine()
    service = engine.service
    appels = {"n": 0}
    original = service.candles

    async def compte(*args, **kwargs):
        appels["n"] += 1
        return await original(*args, **kwargs)

    service.candles = compte  # type: ignore[method-assign]
    await engine.candles("XAUUSD", Timeframe.H1, 100)
    await engine.candles("XAUUSD", Timeframe.H1, 100)
    assert appels["n"] == 1
    # Un rafraichissement explicite redemande la serie au broker.
    await engine.candles("XAUUSD", Timeframe.H1, 100, refresh=True)
    assert appels["n"] == 2


async def test_candles_symbole_inconnu_rend_une_serie_vide() -> None:
    engine = await build_engine()
    assert await engine.candles("INEXISTANT", Timeframe.H1, 50) == []
    assert await engine.candles("XAUUSD", "H7", 50) == []
    assert await engine.candles("", Timeframe.H1, 50) == []


async def test_candles_survivent_a_une_panne_du_terminal() -> None:
    engine = await build_engine()

    async def explose(*args, **kwargs):
        raise RuntimeError("terminal absent")

    engine.service.candles = explose  # type: ignore[method-assign]
    assert await engine.candles("XAUUSD", Timeframe.H1, 50) == []
    assert engine.errors == 1
    assert engine.last_error == "terminal absent"


async def test_atr_et_quote() -> None:
    engine = await build_engine()
    atr = await engine.atr("XAUUSD", Timeframe.H1)
    assert atr is not None and atr > 0
    assert await engine.atr("INEXISTANT", Timeframe.H1) is None

    quote = await engine.quote("XAUUSD")
    assert quote is not None
    assert quote.bid is not None and quote.ask is not None
    assert quote.ask >= quote.bid
    assert quote.spread_points == 20
    assert quote.mid == pytest.approx((quote.bid + quote.ask) / 2)
    assert await engine.quote("INEXISTANT") is None


async def test_symboles_disponibles_et_metadonnees() -> None:
    engine = await build_engine()
    symbols = await engine.available_symbols()
    assert "XAUUSD" in symbols
    assert symbols == sorted(symbols)
    assert await engine.is_available("XAUUSD") is True
    assert await engine.is_available("INEXISTANT") is False
    info = await engine.symbol_info("XAUUSD")
    assert info is not None and info.digits == 2


async def test_market_state_ouvert_et_inconnu() -> None:
    engine = await build_engine()
    state = await engine.market_state("XAUUSD")
    assert state.status == "OPEN"
    assert state.tradable is True
    assert state.last_candle_at is not None

    inconnu = await engine.market_state("INEXISTANT")
    assert inconnu.status == "UNKNOWN"
    assert inconnu.quote is None
    assert "introuvable" in inconnu.detail.lower() or "inconnu" in inconnu.detail.lower()


async def test_invalidation_et_statistiques() -> None:
    engine = await build_engine()
    await engine.candles("XAUUSD", Timeframe.H1, 50)
    await engine.symbol_info("XAUUSD")
    engine.invalidate("XAUUSD")
    stats = engine.stats()
    assert stats["candleCache"]["entries"] == 0
    assert stats["metadataEntries"] == 0
    engine.invalidate()
    assert engine.stats()["symbolsCached"] == 0


async def test_provider_rend_le_moteur_du_service_actif(paper) -> None:
    reset_market_engine()
    first = market_engine()
    assert first is not None
    assert market_engine() is first
    # Un autre service donne un autre moteur : aucun cache n'est partage.
    autre = FakeMetaTraderService()
    assert market_engine(autre) is not first
    reset_market_engine()


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

async def test_catalogue_ne_retient_que_les_symboles_reels() -> None:
    engine = await build_engine()
    catalogue = await WatchlistService(engine).catalogue()
    assert catalogue["XAUUSD"] == "XAUUSD"
    assert "EURUSD" in catalogue
    # Le simulateur ne propose pas ces instruments : ils sont absents.
    assert "SPX500" not in catalogue
    assert "USDCHF" not in catalogue


async def test_resolution_instrument_inconnu(session: AsyncSession) -> None:
    engine = await build_engine()
    resolution = await WatchlistService(engine).resolve(session, "SPX500")
    assert resolution.available is False
    assert resolution.broker_symbol is None
    assert "introuvable" in resolution.message


async def test_ajout_refuse_un_instrument_absent(session: AsyncSession) -> None:
    engine = await build_engine()
    item, resolution = await WatchlistService(engine).add(session, "SPX500")
    assert item is None
    assert resolution.available is False
    assert await market_repo.list_watchlist(session) == []


async def test_ajout_et_mise_a_jour_d_un_instrument(session: AsyncSession) -> None:
    engine = await build_engine()
    service = WatchlistService(engine)
    item, resolution = await service.add(session, "GOLD", scan_priority=9)
    assert item is not None
    assert item.canonical == "XAUUSD"
    assert item.broker_symbol == "XAUUSD"
    assert item.available is True
    assert item.scan_priority == 9
    assert resolution.available is True

    await market_repo.update_watchlist_item(session, item, {"enabled": False})
    scannables = await service.scannable(session)
    assert scannables == []

    await market_repo.update_watchlist_item(session, item, {"enabled": True})
    assert [entry.canonical for entry in await service.scannable(session)] == ["XAUUSD"]


async def test_suggestions_filtrees_sur_le_catalogue(session: AsyncSession) -> None:
    engine = await build_engine()
    proposees = await WatchlistService(engine).suggested(session)
    noms = {candidate.canonical for candidate in proposees}
    assert "XAUUSD" in noms
    assert noms <= set(DEFAULT_WATCHLIST)
    for candidate in proposees:
        assert candidate.broker_symbol
        assert candidate.digits is not None


async def test_refresh_marque_un_instrument_disparu(session: AsyncSession) -> None:
    engine = await build_engine()
    service = WatchlistService(engine)
    await service.add(session, "XAUUSD")

    # Le broker retire le symbole de son catalogue.
    engine.service.book.symbols.pop("XAUUSD")
    engine.invalidate()
    items = await service.refresh(session)
    assert items[0].available is False
    assert await service.scannable(session) == []


async def test_suppression_de_watchlist(session: AsyncSession) -> None:
    engine = await build_engine()
    await WatchlistService(engine).add(session, "EURUSD")
    assert await market_repo.delete_watchlist_item(session, "EURUSD") is True
    assert await market_repo.delete_watchlist_item(session, "EURUSD") is False
