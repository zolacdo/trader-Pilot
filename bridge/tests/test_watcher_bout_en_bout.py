"""Chaine complete du Market Watcher, du marche simule au message Telegram.

Le simulateur MetaTrader fournit les bougies, le publieur recoit une fonction
d'envoi injectee. Aucun terminal reel, aucun message reel, aucun appel IA :
la lecture IA est desactivee par configuration dans ces tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.intelligence import Timeframe
from app.services.market_data.engine import MarketDataEngine
from app.services.mt5.fake_service import FakeMetaTraderService
from app.watcher import performance, repository
from app.watcher.analysis.context import freshness_tolerance
from app.watcher.config import WatcherConfig, invalidate_cache, load_config, update_config
from app.watcher.engine import WatcherEngine
from app.watcher.models import (
    STRATEGY_VERSION,
    WatcherDecision,
    WatcherSignal,
    WatcherStatus,
)
from app.watcher.publisher import TelegramPublisher

SYMBOL = "XAUUSD"


class Recorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, text: str) -> int:
        self.messages.append(text)
        return len(self.messages)


@pytest.fixture
async def market() -> MarketDataEngine:
    service = FakeMetaTraderService(balance=10000.0)
    await service.initialize()
    return MarketDataEngine(service)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def watcher(recorder: Recorder) -> WatcherEngine:
    return WatcherEngine(TelegramPublisher(sender=recorder))


@pytest.fixture
def config() -> WatcherConfig:
    settings = WatcherConfig()
    # L'IA n'est jamais appelee dans les tests : aucun reseau, aucun quota.
    settings.ai_enabled = False
    settings.send_startup_message = False
    return settings


# ---------------------------------------------------------------------------
# Analyse complete
# ---------------------------------------------------------------------------
class TestAnalyseComplete:
    async def test_une_analyse_produit_toujours_une_decision(
        self, session, market: MarketDataEngine, watcher: WatcherEngine, config: WatcherConfig
    ) -> None:
        outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        assert outcome.decision in set(WatcherDecision)
        assert outcome.detail

    async def test_l_analyse_est_tracee_meme_sans_signal(
        self, session, market: MarketDataEngine, watcher: WatcherEngine, config: WatcherConfig
    ) -> None:
        """Chaque tour laisse une trace : c'est ce qui permet la calibration."""
        await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        trace = await repository.last_analysis(session, SYMBOL)
        assert trace is not None
        assert trace.symbol == SYMBOL
        assert trace.decision in set(WatcherDecision)

    async def test_la_trace_dit_pourquoi_le_score_est_bas(
        self, session, market: MarketDataEngine, watcher: WatcherEngine, config: WatcherConfig
    ) -> None:
        """Sans ces deux valeurs, un score bas est indechiffrable apres coup.

        Le 16/09/2026, repondre a « un critere du score est-il degrade ? » a
        demande de croiser la volatilite et l'amplitude des prix, alors que la
        reponse existait au moment du calcul et etait jetee. La couverture dit
        si un critere a disparu ; le critere le plus faible dit ce qui tire le
        score vers le bas.
        """
        await watcher.analyse(session, market, SYMBOL, SYMBOL, config)

        trace = await repository.last_analysis(session, SYMBOL)
        assert trace is not None
        assert 0.0 < trace.coverage <= 1.0
        assert trace.weakest_criterion, "le critere le plus faible doit etre nomme"

    async def test_un_seuil_atteignable_produit_un_signal_publie(
        self,
        session,
        market: MarketDataEngine,
        watcher: WatcherEngine,
        config: WatcherConfig,
        recorder: Recorder,
        geometrie_permissive: None,
    ) -> None:
        """La garde geometrique est desserree : ce test mesure la publication.

        Les bougies du simulateur ne dependent que du symbole et de
        l'horodatage ABSOLU. Selon l'heure a laquelle la suite tourne, le stop
        calcule tient dans 4 ATR ou non -- et un test qui rougit selon
        l'horloge ne prouve rien le reste du temps.
        """
        config.minimum_score = 1.0
        config.minimum_rr = 0.1
        config.require_entry_confirmation = False  # on mesure la chaine, pas l.entree
        outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        assert outcome.decision.is_tradable, outcome.detail
        assert outcome.signal is not None
        assert outcome.published is True
        assert len(recorder.messages) == 1
        assert SYMBOL in recorder.messages[0]

    async def test_le_signal_enregistre_porte_sa_version_de_strategie(
        self,
        session,
        market: MarketDataEngine,
        watcher: WatcherEngine,
        config: WatcherConfig,
        geometrie_permissive: None,
    ) -> None:
        config.minimum_score = 1.0
        config.minimum_rr = 0.1
        config.require_entry_confirmation = False  # on mesure la chaine, pas l.entree
        outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        assert outcome.signal is not None
        assert outcome.signal.strategy_version == STRATEGY_VERSION
        assert outcome.signal.timeframe
        assert outcome.signal.expires_at is not None

    async def test_les_niveaux_sont_coherents_avec_le_sens(
        self,
        session,
        market: MarketDataEngine,
        watcher: WatcherEngine,
        config: WatcherConfig,
        geometrie_permissive: None,
    ) -> None:
        config.minimum_score = 1.0
        config.minimum_rr = 0.1
        config.require_entry_confirmation = False  # on mesure la chaine, pas l.entree
        outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        signal = outcome.signal
        assert signal is not None
        if signal.direction.value == "BUY":
            assert signal.stop_loss < signal.entry < min(signal.targets)
        else:
            assert signal.stop_loss > signal.entry > max(signal.targets)

    async def test_mode_dry_run_enregistre_sans_publier(
        self,
        session,
        market: MarketDataEngine,
        watcher: WatcherEngine,
        config: WatcherConfig,
        recorder: Recorder,
        geometrie_permissive: None,
    ) -> None:
        config.minimum_score = 1.0
        config.minimum_rr = 0.1
        config.require_entry_confirmation = False  # on mesure la chaine, pas l.entree
        config.dry_run = True
        outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        assert outcome.signal is not None, "le signal est bien calcule et enregistre"
        assert outcome.published is False
        assert recorder.messages == []

    async def test_aucun_doublon_sur_le_meme_sens(
        self,
        session,
        market: MarketDataEngine,
        watcher: WatcherEngine,
        config: WatcherConfig,
        recorder: Recorder,
        geometrie_permissive: None,
    ) -> None:
        """Le second tour ne doit pas republier le meme signal (CDC3 section 31)."""
        config.minimum_score = 1.0
        config.minimum_rr = 0.1
        config.require_entry_confirmation = False  # on mesure la chaine, pas l.entree
        first = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        assert first.published is True

        second = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        assert second.decision is WatcherDecision.NO_TRADE
        assert second.signal is None
        assert len(recorder.messages) == 1

    async def test_symbole_inconnu_ne_leve_pas(
        self, session, market: MarketDataEngine, watcher: WatcherEngine, config: WatcherConfig
    ) -> None:
        outcome = await watcher.analyse(session, market, "INEXISTANT", "INEXISTANT", config)
        assert outcome.decision is WatcherDecision.NO_TRADE
        assert outcome.signal is None
        assert outcome.detail

    async def test_score_impossible_ne_publie_rien(
        self,
        session,
        market: MarketDataEngine,
        watcher: WatcherEngine,
        config: WatcherConfig,
        recorder: Recorder,
    ) -> None:
        config.minimum_score = 100.0
        config.watch_score = 100.0
        outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        assert outcome.decision in (WatcherDecision.NO_TRADE, WatcherDecision.WAIT)
        assert recorder.messages == []


# ---------------------------------------------------------------------------
# Fraicheur des donnees (CDC3 section 66)
# ---------------------------------------------------------------------------
class TestFraicheur:
    def test_la_tolerance_suit_l_unite_de_temps(self, config: WatcherConfig) -> None:
        """Une bougie M15 qui vient de s'ouvrir a legitimement quinze minutes.

        Un plafond fixe plus court que la bougie analysee declarerait les
        donnees perimees en permanence, et aucun signal ne sortirait jamais.
        """
        config.max_data_age_seconds = 600
        assert freshness_tolerance(config, Timeframe.M15) == 1800
        assert freshness_tolerance(config, Timeframe.H1) == 7200
        assert freshness_tolerance(config, Timeframe.H4) == 28800

    def test_le_reglage_reste_un_plancher(self, config: WatcherConfig) -> None:
        """Sur les unites tres courtes, c'est le reglage qui s'applique."""
        config.max_data_age_seconds = 600
        assert freshness_tolerance(config, Timeframe.M1) == 600
        assert freshness_tolerance(config, Timeframe.M5) == 600

    def test_unite_inconnue_retombe_sur_le_reglage(self, config: WatcherConfig) -> None:
        config.max_data_age_seconds = 300
        assert freshness_tolerance(config, None) == 300

    async def test_une_bougie_m15_recente_reste_exploitable(
        self, session, market: MarketDataEngine, watcher: WatcherEngine, config: WatcherConfig
    ) -> None:
        """Verification de bout en bout du correctif : les donnees passent."""
        config.minimum_score = 1.0
        config.minimum_rr = 0.1
        config.require_entry_confirmation = False  # on mesure la chaine, pas l.entree
        outcome = await watcher.analyse(session, market, SYMBOL, SYMBOL, config)
        assert outcome.context is not None
        assert outcome.context.quality.fresh is True
        assert "trop anciennes" not in outcome.detail


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class TestConfiguration:
    async def test_valeurs_par_defaut_utilisables(self, session) -> None:
        invalidate_cache()
        config = await load_config(session, refresh=True)
        assert config.enabled is True
        assert config.symbols
        assert config.telegram_channel
        assert config.minimum_score > config.watch_score

    async def test_modification_prise_en_compte(self, session) -> None:
        invalidate_cache()
        config = await update_config(session, {"minimum_score": 82, "dry_run": True})
        assert config.minimum_score == 82.0
        assert config.dry_run is True
        relu = await load_config(session, refresh=True)
        assert relu.minimum_score == 82.0

    async def test_reglage_inconnu_est_refuse(self, session) -> None:
        invalidate_cache()
        with pytest.raises(ValueError, match="inconnus"):
            await update_config(session, {"seuil_magique": 12})

    async def test_ponderation_partielle_complete_les_defauts(self, session) -> None:
        """Redefinir trois criteres ne doit pas effacer les sept autres."""
        invalidate_cache()
        config = await update_config(session, {"weights": {"sentiment": 25}})
        assert config.weights["sentiment"] == 25.0
        assert config.weights["market_structure"] == 20.0
        assert config.total_weight == pytest.approx(sum(config.weights.values()))

    async def test_valeur_illisible_ne_casse_rien(self, session) -> None:
        from app.repositories import settings_repo

        invalidate_cache()
        await settings_repo.set_setting(session, "watcher.minimum_score", "beaucoup")
        config = await load_config(session, refresh=True)
        assert config.minimum_score == WatcherConfig().minimum_score


# ---------------------------------------------------------------------------
# Statistiques (CDC3 section 40)
# ---------------------------------------------------------------------------
class TestPerformance:
    def _signal(self, result: float | None, score: float = 75.0, **kwargs) -> WatcherSignal:
        from app.models.enums import Direction

        values = {
            "symbol": "XAUUSD",
            "broker_symbol": "XAUUSD",
            "direction": Direction.BUY,
            "decision": WatcherDecision.BUY,
            "status": WatcherStatus.TP3_HIT if (result or 0) > 0 else WatcherStatus.SL_HIT,
            "timeframe": "M15",
            "entry": 100.0,
            "stop_loss": 98.0,
            "risk_distance": 2.0,
            "risk_reward_1": 1.0,
            "score": score,
            "result_r": result,
            "created_at": datetime(2024, 1, 1, 10, tzinfo=UTC),
        }
        values.update(kwargs)
        return WatcherSignal(**values)  # type: ignore[arg-type]

    def test_repli_maximal_mesure_la_pire_descente(self) -> None:
        """Une esperance positive avec un repli brutal n'est pas jouable.

        C'est la mesure qui manquait pour juger la bande mesuree : +0,40 R par
        operation ne dit rien du chemin parcouru pour y arriver.

        Les signaux sont horodates dans l'ordre : le repli se lit sur la
        courbe cumulee, donc la chronologie compte.
        """
        moments = [datetime(2024, 1, 1, 10 + index, tzinfo=UTC) for index in range(4)]
        signaux = [
            self._signal(1.0, created_at=moments[0]),
            self._signal(-1.0, created_at=moments[1]),
            self._signal(-1.0, created_at=moments[2]),
            self._signal(2.0, created_at=moments[3]),
        ]

        report = performance.build_report(signaux, window_days=30)

        # Courbe cumulee 1, 0, -1, 1 : sommet a 1, creux a -1.
        assert report.max_drawdown_r == pytest.approx(2.0)
        assert report.to_dict()["maxDrawdownR"] == pytest.approx(2.0)

    def test_sans_perte_le_repli_est_nul(self) -> None:
        report = performance.build_report(
            [self._signal(1.0), self._signal(2.0)], window_days=30
        )

        assert report.max_drawdown_r == pytest.approx(0.0)

    def test_taux_de_reussite_calcule(self) -> None:
        signaux = [self._signal(3.0), self._signal(3.0), self._signal(-1.0)]
        report = performance.build_report(signaux, window_days=30)
        assert report.overall.trades == 3
        assert report.overall.wins == 2
        assert report.overall.win_rate == pytest.approx(66.7, abs=0.1)
        assert report.overall.total_r == pytest.approx(5.0)

    def test_signal_sans_resultat_n_est_pas_compte_comme_perte(self) -> None:
        """Un signal invalide avant declenchement n'est pas un echec."""
        signaux = [self._signal(None, status=WatcherStatus.INVALIDATED), self._signal(3.0)]
        report = performance.build_report(signaux, window_days=30)
        assert report.overall.trades == 1
        assert report.overall.losses == 0
        assert report.signals_pending_result == 1

    def test_echantillon_trop_court_est_annonce_comme_tel(self) -> None:
        """Aucune conclusion n'est presentee comme etablie sur trois trades."""
        report = performance.build_report([self._signal(3.0)], window_days=30)
        assert report.overall.significant is False
        assert any("trop court" in note for note in report.recommendations)
        assert "trop court" in performance.daily_digest(report)

    def test_series_consecutives(self) -> None:
        signaux = [self._signal(-1.0) for _ in range(3)] + [self._signal(2.0)]
        report = performance.build_report(signaux, window_days=30)
        assert report.max_loss_streak == 3
        assert report.max_win_streak == 1

    def test_ventilation_par_tranche_de_score(self) -> None:
        signaux = [self._signal(2.0, score=72.0), self._signal(-1.0, score=95.0)]
        report = performance.build_report(signaux, window_days=30)
        assert "70-79" in report.by_score
        assert "90-100" in report.by_score

    def test_bilan_vide_ne_leve_pas(self) -> None:
        report = performance.build_report([], window_days=7)
        assert report.overall.trades == 0
        assert "Aucun signal" in performance.daily_digest(report)


# ---------------------------------------------------------------------------
# Ordonnanceur
# ---------------------------------------------------------------------------
class TestOrdonnanceur:
    def test_le_balayage_tourne_pour_ne_starver_personne(self) -> None:
        """MetaTrader peut mourir en plein cycle : l'ordre ne doit pas etre fige.

        Sans rotation, les memes instruments de fin de liste ne seraient jamais
        analyses des que le terminal cesse de repondre en cours de tour.
        """
        from app.watcher.scheduler import WatcherScheduler

        scheduler = WatcherScheduler(TelegramPublisher(sender=Recorder()))
        disponibles = {"A": "Am", "B": "Bm", "C": "Cm"}
        premiers = [scheduler._rotated(disponibles)[0][0] for _ in range(3)]
        assert premiers == ["A", "B", "C"]

    def test_une_analyse_ciblee_ne_tourne_pas(self) -> None:
        """Une demande explicite garde l'ordre demande."""
        from app.watcher.scheduler import WatcherScheduler

        scheduler = WatcherScheduler(TelegramPublisher(sender=Recorder()))
        disponibles = {"A": "Am", "B": "Bm"}
        assert scheduler._rotated(disponibles, rotate=False)[0][0] == "A"
        assert scheduler._rotated(disponibles, rotate=False)[0][0] == "A"

    async def test_les_boucles_demarrent_et_s_arretent_proprement(self) -> None:
        from app.watcher.scheduler import WatcherScheduler

        scheduler = WatcherScheduler(TelegramPublisher(sender=Recorder()))
        scheduler.start()
        assert scheduler.started is True
        assert len(scheduler.state.to_dict()["loops"]) == 4
        await scheduler.stop()
        assert scheduler.started is False


# ---------------------------------------------------------------------------
# Etancheite du sous-systeme
# ---------------------------------------------------------------------------
class TestEtancheite:
    def test_le_watcher_n_importe_aucun_moteur_d_execution(self) -> None:
        """Le watcher ne peut pas passer d'ordre : c'est structurel (CDC3 44)."""
        import pathlib

        racine = pathlib.Path(__file__).resolve().parents[1] / "app" / "watcher"
        interdits = ("trading.executor", "trading.engine", "order_send", "mt5_orders")
        for fichier in racine.rglob("*.py"):
            contenu = fichier.read_text(encoding="utf-8")
            for motif in interdits:
                assert motif not in contenu, f"{fichier.name} reference {motif}"

    def test_toutes_les_tables_sont_prefixees(self) -> None:
        from app.watcher.models import WatcherAnalysis, WatcherSignal, WatcherSignalEvent

        for modele in (WatcherSignal, WatcherSignalEvent, WatcherAnalysis):
            assert modele.__tablename__.startswith("watcher_")

    async def test_les_tables_du_watcher_existent_en_base(self, session) -> None:
        """Le schema doit etre cree sans intervention : le Bridge s'en charge."""
        rows = await repository.open_signals(session)
        assert rows == []

    async def test_le_moteur_de_donnees_reste_celui_du_bridge(
        self, market: MarketDataEngine
    ) -> None:
        candles = await market.candles(SYMBOL, Timeframe.M15, 100)
        assert len(candles) >= 100
