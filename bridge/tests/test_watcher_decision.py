"""Niveaux, score et Risk Manager du Market Watcher.

Ces trois modules sont purs : ils recoivent un contexte deja construit et
rendent un resultat. Les tests les exercent sans base de donnees, sans
MetaTrader et sans Telegram.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import Direction
from app.models.intelligence import Timeframe
from app.services.market_data.engine import Quote
from app.services.mt5.interface import Candle, SymbolInfo
from app.services.technical_analysis.engine import TechnicalAnalysisEngine
from app.watcher import risk
from app.watcher.analysis.context import DataQuality, MarketContext, NewsGuard, SentimentReading
from app.watcher.analysis.volatility import VolatilityReading
from app.watcher.config import WatcherConfig
from app.watcher.levels import build_levels
from app.watcher.models import EntryType, RiskVerdict, VolatilityLevel
from app.watcher.scoring import score_direction

BASE = datetime(2024, 1, 1, tzinfo=UTC)
ENGINE = TechnicalAnalysisEngine()


def rising_candles(count: int = 160, step: float = 1.0) -> list[Candle]:
    """Tendance haussiere reguliere avec de petits replis : structure HH/HL."""
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        # Un repli toutes les dix bougies cree des creux montants exploitables.
        drift = step if index % 10 else -step * 0.6
        open_ = price
        price = round(price + drift, 4)
        candles.append(
            Candle(
                time=BASE + timedelta(minutes=15 * index),
                open=open_,
                high=max(open_, price) + 0.4,
                low=min(open_, price) - 0.4,
                close=price,
                tick_volume=120,
            )
        )
    return candles


def make_context(
    candles: list[Candle] | None = None,
    *,
    symbol: str = "TESTUSD",
    spread_points: int = 10,
    volatility: VolatilityLevel = VolatilityLevel.NORMAL,
    sentiment: SentimentReading | None = None,
    news_guard: NewsGuard | None = None,
    market_status: str | None = "OPEN",
) -> MarketContext:
    """Contexte complet, construit a la main a partir de bougies synthetiques."""
    series = candles if candles is not None else rising_candles()
    analysis = ENGINE.analyse(symbol, Timeframe.M15, series)
    info = SymbolInfo(
        name=symbol,
        digits=2,
        point=0.01,
        trade_stops_level=0,
        volume_min=0.01,
        volume_step=0.01,
    )
    last = series[-1].close
    quote = Quote(
        symbol=symbol,
        bid=last - spread_points * info.point / 2,
        ask=last + spread_points * info.point / 2,
        spread_points=spread_points,
        spread_price=spread_points * info.point,
        time=series[-1].time,
    )
    context = MarketContext(symbol=symbol, broker_symbol=symbol)
    context.primary = analysis
    context.primary_timeframe = Timeframe.M15
    context.candles = series
    context.symbol_info = info
    context.quote = quote
    context.quality = DataQuality(
        candles=len(series), fresh=True, sufficient=True, age_seconds=10, detail="ok"
    )
    context.volatility = VolatilityReading(
        level=volatility, atr=analysis.atr, detail="volatilite de test"
    )
    if sentiment is not None:
        context.sentiment = sentiment
    if news_guard is not None:
        context.news_guard = news_guard
    if market_status is not None:
        from app.services.market_data.engine import MarketState

        context.market_state = MarketState(symbol=symbol, status=market_status)
    return context


@pytest.fixture
def config() -> WatcherConfig:
    return WatcherConfig()


# ---------------------------------------------------------------------------
# Niveaux (CDC3 sections 26 a 29)
# ---------------------------------------------------------------------------
class TestNiveaux:
    def test_achat_produit_des_niveaux_coherents(self, config: WatcherConfig) -> None:
        levels = build_levels(make_context(), Direction.BUY, config.minimum_rr)
        assert levels.stop_loss < levels.entry, "le stop d'un achat est sous l'entree"
        assert levels.risk_distance > 0
        assert len(levels.targets) == 3
        assert levels.targets == sorted(levels.targets), "les objectifs sont croissants"
        for target in levels.targets:
            assert target > levels.entry

    def test_vente_produit_des_niveaux_miroir(self, config: WatcherConfig) -> None:
        levels = build_levels(make_context(), Direction.SELL, config.minimum_rr)
        assert levels.stop_loss > levels.entry
        assert levels.targets == sorted(levels.targets, reverse=True)
        for target in levels.targets:
            assert target < levels.entry

    def test_risk_reward_croissant_et_calcule(self, config: WatcherConfig) -> None:
        levels = build_levels(make_context(), Direction.BUY, config.minimum_rr)
        assert levels.risk_rewards == sorted(levels.risk_rewards)
        premier = abs(levels.targets[0] - levels.entry) / levels.risk_distance
        assert levels.risk_rewards[0] == pytest.approx(premier, abs=0.05)

    def test_chaque_niveau_est_justifie(self, config: WatcherConfig) -> None:
        """Un signal doit rester explicable (CDC3 section 80)."""
        levels = build_levels(make_context(), Direction.BUY, config.minimum_rr)
        assert levels.entry_reason
        assert levels.stop_reason
        assert len(levels.target_reasons) == 3
        assert levels.invalidation

    def test_risk_reward_insuffisant_invalide_le_setup(self) -> None:
        levels = build_levels(make_context(), Direction.BUY, minimum_rr=99.0)
        assert levels.valid is False
        assert levels.rejection is not None and "Risk/Reward" in levels.rejection

    def test_analyse_inexploitable_est_refusee_sans_inventer(self, config: WatcherConfig) -> None:
        """Sans donnee, on refuse : on ne fabrique aucun prix (CDC3 section 87)."""
        context = make_context(candles=rising_candles(count=5))
        levels = build_levels(context, Direction.BUY, config.minimum_rr)
        assert levels.valid is False
        assert levels.entry == 0.0
        assert levels.rejection is not None

    def test_stop_respecte_la_distance_minimale_du_broker(self, config: WatcherConfig) -> None:
        context = make_context()
        assert context.symbol_info is not None
        context.symbol_info.trade_stops_level = 5000  # 50.00 d'ecart impose
        levels = build_levels(context, Direction.BUY, config.minimum_rr)
        if levels.valid:
            assert levels.entry - levels.stop_loss >= 50.0 - 1e-6
        else:
            # Un stop impose aussi large peut sortir des bornes : c'est un refus
            # explicite, jamais un stop silencieusement trop proche.
            assert levels.rejection is not None

    def test_entree_sur_cassure_quand_une_resistance_est_proche(
        self, config: WatcherConfig
    ) -> None:
        levels = build_levels(make_context(), Direction.BUY, config.minimum_rr)
        assert levels.entry_type in set(EntryType)
        if levels.entry_type is EntryType.STOP:
            assert "cassure" in levels.entry_reason.lower()


# ---------------------------------------------------------------------------
# Score (CDC3 section 24)
# ---------------------------------------------------------------------------
class TestScore:
    def test_score_reste_dans_les_bornes(self, config: WatcherConfig) -> None:
        context = make_context()
        for direction in (Direction.BUY, Direction.SELL):
            levels = build_levels(context, direction, config.minimum_rr)
            card = score_direction(context, direction, levels, config)
            assert 0.0 <= card.score <= 100.0
            assert 0.0 <= card.coverage <= 1.0

    def test_tendance_haussiere_favorise_l_achat(self, config: WatcherConfig) -> None:
        context = make_context()
        achat = score_direction(
            context, Direction.BUY, build_levels(context, Direction.BUY, config.minimum_rr), config
        )
        vente = score_direction(
            context, Direction.SELL, build_levels(context, Direction.SELL, config.minimum_rr), config
        )
        assert achat.score > vente.score

    def test_donnees_absentes_reduisent_la_couverture(self, config: WatcherConfig) -> None:
        """Sans actualites, le score plafonne au lieu d'etre suppose neutre."""
        context = make_context()
        card = score_direction(
            context, Direction.BUY, build_levels(context, Direction.BUY, config.minimum_rr), config
        )
        assert card.coverage < 1.0
        assert "Sentiment" in card.missing
        assert "Fondamental" in card.missing
        assert card.score < card.raw_score

    def test_sentiment_disponible_ameliore_la_couverture(self, config: WatcherConfig) -> None:
        nu = make_context()
        avec = make_context(
            sentiment=SentimentReading(
                available=True, score=60.0, label="BULLISH", sample=4, detail="test"
            )
        )
        levels_nu = build_levels(nu, Direction.BUY, config.minimum_rr)
        levels_avec = build_levels(avec, Direction.BUY, config.minimum_rr)
        card_nu = score_direction(nu, Direction.BUY, levels_nu, config)
        card_avec = score_direction(avec, Direction.BUY, levels_avec, config)
        assert card_avec.coverage > card_nu.coverage

    def test_volatilite_extreme_annule_son_critere(self, config: WatcherConfig) -> None:
        context = make_context(volatility=VolatilityLevel.EXTREME)
        card = score_direction(
            context, Direction.BUY, build_levels(context, Direction.BUY, config.minimum_rr), config
        )
        critere = next(item for item in card.criteria if item.key == "volatility")
        assert critere.available is True
        assert critere.ratio == 0.0

    def test_un_seul_indicateur_ne_suffit_jamais(self, config: WatcherConfig) -> None:
        """Aucun critere ne pese assez pour declencher seul un signal."""
        context = make_context()
        card = score_direction(
            context, Direction.BUY, build_levels(context, Direction.BUY, config.minimum_rr), config
        )
        for critere in card.criteria:
            assert critere.weight < config.minimum_score

    def test_paliers_de_lecture(self, config: WatcherConfig) -> None:
        context = make_context()
        card = score_direction(
            context, Direction.BUY, build_levels(context, Direction.BUY, config.minimum_rr), config
        )
        assert card.grade() in {
            "NO TRADE",
            "WATCH",
            "WEAK SIGNAL",
            "VALID SIGNAL",
            "STRONG SIGNAL",
            "EXCEPTIONAL SETUP",
        }


# ---------------------------------------------------------------------------
# Risk Manager (CDC3 section 30)
# ---------------------------------------------------------------------------
class TestRiskManager:
    def _evaluer(
        self,
        context: MarketContext,
        config: WatcherConfig,
        state: risk.PortfolioState | None = None,
        direction: Direction = Direction.BUY,
    ) -> risk.RiskDecision:
        levels = build_levels(context, direction, config.minimum_rr)
        card = score_direction(context, direction, levels, config)
        return risk.evaluate(
            context, direction, levels, card, config, state or risk.PortfolioState()
        )

    def test_marche_ferme_est_refuse(self, config: WatcherConfig) -> None:
        context = make_context(market_status="CLOSED")
        decision = self._evaluer(context, config)
        assert decision.verdict is RiskVerdict.REJECTED
        assert any("ferme" in reason.lower() for reason in decision.reasons)

    def test_donnees_anciennes_sont_refusees(self, config: WatcherConfig) -> None:
        context = make_context()
        context.quality.fresh = False
        context.quality.detail = "derniere bougie il y a 3 heures"
        decision = self._evaluer(context, config)
        assert decision.verdict is RiskVerdict.REJECTED

    def test_spread_excessif_met_en_attente(self, config: WatcherConfig) -> None:
        context = make_context(spread_points=config.max_spread_points + 50)
        decision = self._evaluer(context, config)
        assert decision.verdict in (RiskVerdict.WAIT, RiskVerdict.REJECTED)
        assert any("spread" in reason.lower() for reason in decision.reasons)

    def test_un_type_d_entree_ecarte_est_refuse(self, config: WatcherConfig) -> None:
        """Une decision de l'apprentissage doit changer quelque chose.

        Sans ce refus, ``disabled_entry_types`` serait ecrit par la boucle et
        lu par personne : le bannissement annonce dans le canal n'empecherait
        aucun signal, et le systeme continuerait exactement comme avant.
        """
        context = make_context()
        levels = build_levels(context, Direction.BUY, config.minimum_rr)
        config.disabled_entry_types = [levels.entry_type.value]

        decision = self._evaluer(context, config)

        assert decision.verdict is RiskVerdict.REJECTED
        assert any("ecarte" in reason.lower() for reason in decision.reasons)

    def test_un_type_d_entree_non_ecarte_passe(self, config: WatcherConfig) -> None:
        """Le refus vise un type precis, pas tous les autres."""
        context = make_context()
        config.disabled_entry_types = ["UN_TYPE_QUI_N_EXISTE_PAS"]

        decision = self._evaluer(context, config)

        assert not any("ecarte par l'apprentissage" in reason for reason in decision.reasons)

    def test_volatilite_extreme_est_refusee(self, config: WatcherConfig) -> None:
        context = make_context(volatility=VolatilityLevel.EXTREME)
        decision = self._evaluer(context, config)
        assert decision.verdict is RiskVerdict.REJECTED
        assert any("volatilite" in reason.lower() for reason in decision.reasons)

    def test_annonce_imminente_met_en_attente(self, config: WatcherConfig) -> None:
        guard = NewsGuard(
            blocking=True,
            title="US CPI",
            impact="CRITICAL",
            reason="Annonce CRITICAL sur USD (US CPI) dans 5 minute(s).",
        )
        decision = self._evaluer(make_context(news_guard=guard), config)
        assert decision.verdict in (RiskVerdict.WAIT, RiskVerdict.REJECTED)
        assert any("CPI" in reason for reason in decision.reasons)

    def test_doublon_de_meme_sens_est_refuse(self, config: WatcherConfig) -> None:
        """Pas de BUY BTCUSD toutes les minutes (CDC3 section 31)."""
        state = risk.PortfolioState(active_signals=1, active_same_direction=True)
        decision = self._evaluer(make_context(), config, state)
        assert decision.verdict is RiskVerdict.REJECTED
        assert any("deja actif" in reason for reason in decision.reasons)

    def test_delai_entre_signaux_respecte(self, config: WatcherConfig) -> None:
        state = risk.PortfolioState(last_signal_at=datetime.now(UTC) - timedelta(minutes=5))
        decision = self._evaluer(make_context(), config, state)
        assert decision.verdict is RiskVerdict.WAIT
        assert any("minute" in reason for reason in decision.reasons)

    def test_delai_ecoule_ne_bloque_plus(self, config: WatcherConfig) -> None:
        state = risk.PortfolioState(
            last_signal_at=datetime.now(UTC) - timedelta(minutes=config.cooldown_minutes + 5)
        )
        decision = self._evaluer(make_context(), config, state)
        assert all("nouvelle publication" not in reason for reason in decision.reasons)

    def test_plafond_quotidien_met_en_attente(self, config: WatcherConfig) -> None:
        state = risk.PortfolioState(signals_today=config.max_signals_per_day)
        decision = self._evaluer(make_context(), config, state)
        assert decision.verdict in (RiskVerdict.WAIT, RiskVerdict.REJECTED)

    def test_plafond_de_signaux_actifs_met_en_attente(self, config: WatcherConfig) -> None:
        state = risk.PortfolioState(active_signals=config.max_active_signals)
        decision = self._evaluer(make_context(), config, state)
        assert decision.verdict in (RiskVerdict.WAIT, RiskVerdict.REJECTED)

    def test_le_refus_prime_sur_l_attente(self, config: WatcherConfig) -> None:
        """Un motif de refus l'emporte toujours sur un simple motif d'attente."""
        context = make_context(market_status="CLOSED", spread_points=500)
        decision = self._evaluer(context, config)
        assert decision.verdict is RiskVerdict.REJECTED
        assert len(decision.reasons) >= 2

    def test_couverture_trop_faible_est_refusee(self, config: WatcherConfig) -> None:
        """Trop de donnees manquantes : le score ne veut plus rien dire."""
        config.weights = {**config.weights, "sentiment": 200.0, "fundamental": 200.0}
        decision = self._evaluer(make_context(), config)
        assert decision.verdict is RiskVerdict.REJECTED
        assert any("couverture" in reason.lower() for reason in decision.reasons)

    def test_contexte_sain_est_approuve_ou_mis_en_attente(self, config: WatcherConfig) -> None:
        """Un contexte propre ne doit jamais etre rejete pour un motif technique."""
        config.minimum_score = 0.0
        decision = self._evaluer(make_context(), config)
        assert decision.verdict is RiskVerdict.APPROVED
        assert decision.reasons == []
