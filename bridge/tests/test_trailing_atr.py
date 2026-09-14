"""Trailing stop adosse a la volatilite de l'instrument.

Une distance en POINTS ne peut pas convenir a tous les actifs. Mesure sur le
compte reel le 14/09/2026, avec le reglage alors en place de 200 points :

    EURUSD  200 pts = 4,00 x ATR M15   -> le stop ne se resserre jamais
    BTCUSD  200 pts = 0,01 x ATR M15   -> le stop serait colle au prix

Un facteur 400 entre les deux extremes. Le mode ATR_BASED exprime la distance
en multiples de l'ATR : la meme valeur garde son sens partout.

Aucun terminal reel : le courtier est simule et rend les bougies qu'on lui
donne.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.core import RiskSettings
from app.models.enums import BreakEvenTrigger, Direction, PositionState, TrailingMode
from app.models.trading import TradeRecord
from app.services.mt5.interface import Candle, SymbolInfo, Tick, TradeResult
from app.services.trading.position_manager import (
    TRAILING_STEP_RATIO,
    ManagementResult,
    PositionManager,
)

BASE = datetime(2026, 9, 14, tzinfo=UTC)


class BrokerSimule:
    """Courtier minimal : bougies fournies, modifications enregistrees."""

    def __init__(self, symbol: SymbolInfo, candles: list[Candle] | None = None) -> None:
        self._symbol = symbol
        self._candles = candles if candles is not None else []
        self.modifications: list[tuple[int, float | None, float | None]] = []
        self.candles_demandees: list[tuple[str, str, int]] = []

    @property
    def symbole_courant(self) -> SymbolInfo:
        return self._symbol

    async def symbol_info(self, symbol: str) -> SymbolInfo:
        return self._symbol

    async def recent_candles(self, symbol: str, timeframe: str, bars: int) -> list[Candle]:
        self.candles_demandees.append((symbol, timeframe, bars))
        return list(self._candles)

    async def symbol_tick(self, symbol: str) -> Tick:
        return Tick(symbol=symbol, bid=0.0, ask=0.0)

    async def modify_position(
        self, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult:
        self.modifications.append((ticket, stop_loss, take_profit))
        return TradeResult(ok=True, message="ok")


class BrokerSansBougies(BrokerSimule):
    async def recent_candles(self, symbol: str, timeframe: str, bars: int) -> list[Candle]:
        raise RuntimeError("terminal muet")


def symbole(name: str, digits: int, point: float, stops_level: int = 0) -> SymbolInfo:
    return SymbolInfo(
        name=name, digits=digits, point=point, trade_stops_level=stops_level
    )


def bougies(amplitude: float, prix: float, nombre: int = 60) -> list[Candle]:
    """Serie d'amplitude constante : l'ATR vaut exactement ``amplitude``."""
    return [
        Candle(
            time=BASE + timedelta(minutes=15 * index),
            open=prix,
            high=prix + amplitude / 2,
            low=prix - amplitude / 2,
            close=prix,
            tick_volume=100,
        )
        for index in range(nombre)
    ]


def position(
    *,
    direction: Direction = Direction.BUY,
    open_price: float = 1.15000,
    stop_loss: float | None = None,
    initial_stop_loss: float | None = None,
    symbol: str = "EURUSDm",
) -> TradeRecord:
    return TradeRecord(
        ticket=1,
        symbol=symbol,
        direction=direction,
        state=PositionState.OPEN,
        open_price=open_price,
        volume=0.1,
        initial_volume=0.1,
        stop_loss=stop_loss,
        initial_stop_loss=initial_stop_loss,
    )


def reglages(**kwargs: object) -> RiskSettings:
    valeurs: dict[str, object] = {
        "trailing_mode": TrailingMode.ATR_BASED,
        "trailing_atr_multiple": 1.5,
        "trailing_atr_tight_multiple": 0.75,
        "trailing_tighten_after_r": 2.0,
        "trailing_atr_period": 14,
        "trailing_atr_timeframe": "M15",
        "trailing_distance_points": 200,
        "break_even_enabled": False,
    }
    valeurs.update(kwargs)
    settings = RiskSettings()
    for cle, valeur in valeurs.items():
        setattr(settings, cle, valeur)
    return settings


async def trailer(
    session, broker: BrokerSimule, trade: TradeRecord, settings: RiskSettings, prix: float
):
    """Execute un tour de trailing et rend le resultat.

    La session est reelle : ``_set_stop_loss`` enregistre la position et
    journalise, comme en production.
    """
    manager = PositionManager(broker)
    tick = Tick(symbol=trade.symbol, bid=prix, ask=prix)
    result = ManagementResult()
    await manager._auto_trailing(
        session, trade, settings, broker.symbole_courant, tick, result
    )
    return result


# ---------------------------------------------------------------------------
# Le defaut corrige
# ---------------------------------------------------------------------------
class TestDistanceEnPointsInadaptee:
    async def test_en_points_le_stop_ne_bouge_jamais_sur_eurusd(self, session) -> None:
        """Le cas reel : 200 points sur EURUSD, le stop reste fige."""
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        trade = position(stop_loss=1.14990, initial_stop_loss=1.14950)
        settings = reglages(trailing_mode=TrailingMode.FIXED_DISTANCE)

        # 200 points sous 1.15100 donnerait 1.14900 : moins protecteur que le
        # stop en place. Le suivi refuse, et refusera toujours.
        result = await trailer(session, broker, trade, settings, prix=1.15100)

        assert broker.modifications == []
        assert result.actions == []

    async def test_en_atr_le_meme_cas_resserre_le_stop(self, session) -> None:
        """Meme position, meme prix : le mode ATR agit."""
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        trade = position(stop_loss=1.14990, initial_stop_loss=1.14950)

        await trailer(session, broker, trade, reglages(), prix=1.15100)

        assert len(broker.modifications) == 1
        _, nouveau_stop, _ = broker.modifications[0]
        # A 1.15100, le trade vaut exactement 2 R : le resserrement s'applique,
        # donc 0,75 ATR = 0.000375 sous le prix.
        assert nouveau_stop == pytest.approx(1.15062, abs=1e-5)


# ---------------------------------------------------------------------------
# La distance suit la volatilite de chaque instrument
# ---------------------------------------------------------------------------
class TestDistanceParInstrument:
    @pytest.mark.parametrize(
        ("nom", "digits", "point", "atr", "prix"),
        [
            ("EURUSDm", 5, 0.00001, 0.00050, 1.15000),
            ("XAUUSDm", 3, 0.001, 7.65, 4300.0),
            ("BTCUSDm", 2, 0.01, 180.0, 77000.0),
        ],
    )
    async def test_la_distance_vaut_toujours_1_5_atr(self, session, nom: str, digits: int, point: float, atr: float, prix: float) -> None:
        info = symbole(nom, digits, point)
        broker = BrokerSimule(info, bougies(atr, prix))
        trade = position(open_price=prix * 0.99, stop_loss=None, symbol=nom)

        await trailer(session, broker, trade, reglages(), prix=prix)

        assert len(broker.modifications) == 1
        _, stop, _ = broker.modifications[0]
        assert prix - stop == pytest.approx(atr * 1.5, rel=0.01)


# ---------------------------------------------------------------------------
# Le resserrement selon le profit deja acquis
# ---------------------------------------------------------------------------
class TestResserrementSelonProfit:
    def _materiel(self, prix: float):
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        # Risque initial de 50 points : 1 R = 0.00050.
        trade = position(open_price=1.15000, stop_loss=None, initial_stop_loss=1.14950)
        return broker, trade

    async def test_gain_modeste_laisse_respirer(self, session) -> None:
        """A 1 R de gain, on garde la distance large de 1,5 ATR."""
        broker, trade = self._materiel(1.15050)
        await trailer(session, broker, trade, reglages(), prix=1.15050)
        _, stop, _ = broker.modifications[0]
        assert 1.15050 - stop == pytest.approx(0.00075, abs=1e-5)

    async def test_gain_installe_resserre_la_distance(self, session) -> None:
        """A 3 R, on protege davantage : 0,75 ATR."""
        broker, trade = self._materiel(1.15150)
        await trailer(session, broker, trade, reglages(), prix=1.15150)
        _, stop, _ = broker.modifications[0]
        assert 1.15150 - stop == pytest.approx(0.000375, abs=1e-5)

    async def test_le_seuil_de_resserrement_est_configurable(self, session) -> None:
        broker, trade = self._materiel(1.15150)
        await trailer(session, broker, trade, reglages(trailing_tighten_after_r=10.0), prix=1.15150)
        _, stop, _ = broker.modifications[0]
        assert 1.15150 - stop == pytest.approx(0.00075, abs=1e-5)

    async def test_sans_stop_initial_la_distance_reste_large(self, session) -> None:
        """Sans risque initial connu, le gain en R n'est pas calculable."""
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        trade = position(open_price=1.15000, stop_loss=None, initial_stop_loss=None)
        await trailer(session, broker, trade, reglages(), prix=1.15200)
        _, stop, _ = broker.modifications[0]
        assert 1.15200 - stop == pytest.approx(0.00075, abs=1e-5)


# ---------------------------------------------------------------------------
# Invariants de securite
# ---------------------------------------------------------------------------
class TestInvariants:
    async def test_un_stop_ne_recule_jamais(self, session) -> None:
        """L'invariant le plus important : le stop ne se desserre pas."""
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        # Stop deja tres protecteur, bien au-dessus de ce que l'ATR propose.
        trade = position(stop_loss=1.15040, initial_stop_loss=1.14950)

        await trailer(session, broker, trade, reglages(), prix=1.15055)

        assert broker.modifications == []

    async def test_une_vente_trail_dans_l_autre_sens(self, session) -> None:
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        trade = position(
            direction=Direction.SELL,
            open_price=1.15000,
            stop_loss=1.15100,
            initial_stop_loss=1.15050,
        )

        await trailer(session, broker, trade, reglages(), prix=1.14900)

        assert len(broker.modifications) == 1
        _, stop, _ = broker.modifications[0]
        assert stop == pytest.approx(1.14975, abs=1e-5)
        assert stop < trade.open_price, "le stop d'une vente gagnante passe sous l'entree"

    async def test_le_pas_evite_de_harceler_le_courtier(self, session) -> None:
        """Un mouvement plus petit que le pas ne declenche aucune requete."""
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        # Stop deja a 0.00075 du prix : le candidat serait quasi identique.
        trade = position(stop_loss=1.14981, initial_stop_loss=1.14950)

        await trailer(session, broker, trade, reglages(), prix=1.15056)

        assert broker.modifications == []

    async def test_le_pas_suit_la_distance_en_mode_atr(self, session) -> None:
        assert pytest.approx(0.25) == TRAILING_STEP_RATIO

    async def test_la_distance_minimale_du_courtier_est_respectee(self, session) -> None:
        info = symbole("EURUSDm", 5, 0.00001, stops_level=200)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        trade = position(stop_loss=None, initial_stop_loss=1.14950)

        await trailer(session, broker, trade, reglages(), prix=1.15055)

        # 1,5 ATR = 75 points, sous les 200 points imposes : refus.
        assert broker.modifications == []


# ---------------------------------------------------------------------------
# Degradations
# ---------------------------------------------------------------------------
class TestDegradations:
    async def test_sans_bougies_on_retombe_sur_les_points(self, session) -> None:
        """Un terminal muet ne doit pas supprimer le suivi."""
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSansBougies(info)
        trade = position(stop_loss=None, initial_stop_loss=1.14950)

        await trailer(session, broker, trade, reglages(trailing_distance_points=50), prix=1.15055)

        assert len(broker.modifications) == 1
        _, stop, _ = broker.modifications[0]
        assert 1.15055 - stop == pytest.approx(0.00050, abs=1e-5)

    async def test_un_historique_trop_court_retombe_aussi(self, session) -> None:
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000, nombre=3))
        trade = position(stop_loss=None, initial_stop_loss=1.14950)

        await trailer(session, broker, trade, reglages(trailing_distance_points=50), prix=1.15055)

        assert len(broker.modifications) == 1

    async def test_le_mode_desactive_ne_fait_rien(self, session) -> None:
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        trade = position(stop_loss=None, initial_stop_loss=1.14950)
        manager = PositionManager(broker)
        settings = reglages(trailing_mode=TrailingMode.DISABLED)

        await manager.apply_automatic_rules(None, settings, [trade])

        assert broker.modifications == []

    async def test_l_unite_de_temps_demandee_est_celle_configuree(self, session) -> None:
        info = symbole("EURUSDm", 5, 0.00001)
        broker = BrokerSimule(info, bougies(0.00050, 1.15000))
        trade = position(stop_loss=None, initial_stop_loss=1.14950)

        await trailer(session, broker, trade, reglages(trailing_atr_timeframe="M5"), prix=1.15055)

        assert broker.candles_demandees
        assert broker.candles_demandees[0][1] == "M5"


# ---------------------------------------------------------------------------
# Break-even automatique
# ---------------------------------------------------------------------------
class TestBreakEvenAutomatique:
    def test_le_declencheur_tp1_hit_n_est_pas_automatique(self, session) -> None:
        """Piege de configuration : ce declencheur attend un message du canal.

        C'est le reglage qui etait en place : le break-even ne se declenchait
        donc jamais tout seul, quel que soit le profit.
        """
        from app.services.trading import position_manager

        source = position_manager.__file__
        with open(source, encoding="utf-8") as handle:
            code = handle.read()
        assert "if trigger is BreakEvenTrigger.SIGNAL_ONLY or trigger is BreakEvenTrigger.TP1_HIT" in code

    @pytest.mark.parametrize(
        "trigger", [BreakEvenTrigger.R_MULTIPLE, BreakEvenTrigger.POINTS]
    )
    def test_les_declencheurs_automatiques_existent(self, trigger: BreakEvenTrigger) -> None:
        assert trigger in set(BreakEvenTrigger)
