"""Publication Telegram, formatage des messages et suivi du cycle de vie.

Regle absolue de cette suite : aucun message reel ne part. Le publieur recoit
une fonction d'envoi injectee qui se contente d'enregistrer les textes
(CDC3 section 61).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import Direction
from app.models.intelligence import Timeframe
from app.services.mt5.interface import Candle
from app.watcher import repository
from app.watcher.config import WatcherConfig
from app.watcher.formatter import detailed_signal, price, signal_message, simple_signal
from app.watcher.lifecycle import LifecycleTracker
from app.watcher.models import EntryType, WatcherDecision, WatcherSignal, WatcherStatus
from app.watcher.publisher import TelegramPublisher

BASE = datetime(2024, 1, 1, tzinfo=UTC)


class Recorder:
    """Fonction d'envoi injectee : elle garde les textes, elle n'envoie rien."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, text: str) -> int:
        self.messages.append(text)
        return len(self.messages)


class FakeCandleEngine:
    """Moteur de bougies minimal : rend toujours la serie qu'on lui a donnee."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles
        self.service = None

    async def candles(self, symbol: str, timeframe: Timeframe, bars: int) -> list[Candle]:
        return list(self._candles)


def make_signal(**overrides: object) -> WatcherSignal:
    """Signal d'achat simple : entree 100, stop 98, objectifs 102 / 104 / 106."""
    values: dict[str, object] = {
        "symbol": "TESTUSD",
        "broker_symbol": "TESTUSD",
        "direction": Direction.BUY,
        "decision": WatcherDecision.BUY,
        "status": WatcherStatus.CONFIRMED,
        "timeframe": "M15",
        "entry_type": EntryType.MARKET,
        "entry": 100.0,
        "stop_loss": 98.0,
        "digits": 2,
        "take_profit_1": 102.0,
        "take_profit_2": 104.0,
        "take_profit_3": 106.0,
        "risk_distance": 2.0,
        "risk_reward_1": 1.0,
        "risk_reward_2": 2.0,
        "risk_reward_3": 3.0,
        "score": 78.0,
        "confidence": 78,
        "timeframe_states": {"H1": "BULLISH", "M15": "BULLISH", "M5": "NEUTRAL"},
        "reasons": ["Structure haussiere confirmee."],
        "risks": ["H4 encore neutre."],
        "invalidation": "Cloture M15 sous 98.00",
        "created_at": BASE,
        "expires_at": BASE + timedelta(hours=4),
    }
    values.update(overrides)
    return WatcherSignal(**values)  # type: ignore[arg-type]


def candles_reaching(high: float, low: float, start: datetime | None = None) -> list[Candle]:
    """Une bougie qui balaie la plage demandee, posterieure a la creation."""
    moment = start or (BASE + timedelta(minutes=1))
    return [Candle(time=moment, open=100.0, high=high, low=low, close=100.0, tick_volume=10)]


@pytest.fixture
def config() -> WatcherConfig:
    return WatcherConfig()


# ---------------------------------------------------------------------------
# Formatage (CDC3 sections 33 et 34)
# ---------------------------------------------------------------------------
class TestFormatage:
    def test_format_simple_tient_en_six_lignes(self) -> None:
        texte = simple_signal(make_signal())
        lignes = texte.splitlines()
        assert lignes[0] == "BUY TESTUSD"
        assert lignes[1] == "Entry 100.00"
        assert lignes[2] == "SL 98.00"
        assert len(lignes) == 6

    def test_format_detaille_contient_tout_le_necessaire(self) -> None:
        texte = detailed_signal(make_signal())
        for attendu in ("TESTUSD", "100.00", "98.00", "102.00", "78/100", "Invalidation"):
            assert attendu in texte

    def test_format_detaille_annonce_qu_aucun_ordre_n_est_passe(self) -> None:
        """Le message ne doit jamais laisser croire a une execution."""
        assert "aucun ordre n'est passe" in detailed_signal(make_signal()).lower()

    def test_le_choix_du_format_est_respecte(self) -> None:
        signal = make_signal()
        assert signal_message(signal, simple=True) == simple_signal(signal)
        assert signal_message(signal, simple=False) == detailed_signal(signal)

    def test_les_textes_externes_sont_echappes(self) -> None:
        """Un titre contenant du HTML ne doit pas casser le message."""
        signal = make_signal(reasons=["<script>alerte</script> & suite"])
        texte = detailed_signal(signal)
        assert "<script>" not in texte
        assert "&lt;script&gt;" in texte

    def test_precision_d_affichage_suit_le_broker(self) -> None:
        assert price(1.23456, 5) == "1.23456"
        assert price(77345.0, 0).replace(" ", " ") == "77 345"

    def test_objectifs_absents_ne_sont_pas_inventes(self) -> None:
        signal = make_signal(take_profit_2=None, take_profit_3=None)
        texte = simple_signal(signal)
        assert "TP1" in texte
        assert "TP2" not in texte


# ---------------------------------------------------------------------------
# Publieur
# ---------------------------------------------------------------------------
class TestPublieur:
    async def test_mode_dry_run_n_envoie_rien(self, session, config: WatcherConfig) -> None:
        recorder = Recorder()
        publisher = TelegramPublisher(sender=recorder)
        config.dry_run = True
        result = await publisher.publish(session, "message", config)
        assert result.sent is False
        assert recorder.messages == []
        assert "dry_run" in (result.reason or "")

    async def test_envoi_normal_passe_par_la_fonction_injectee(
        self, session, config: WatcherConfig
    ) -> None:
        recorder = Recorder()
        publisher = TelegramPublisher(sender=recorder)
        result = await publisher.publish(session, "bonjour", config)
        assert result.sent is True
        assert recorder.messages == ["bonjour"]
        assert publisher.status()["sentCount"] == 1

    async def test_message_vide_est_refuse(self, session, config: WatcherConfig) -> None:
        publisher = TelegramPublisher(sender=Recorder())
        assert (await publisher.publish(session, "   ", config)).sent is False

    async def test_message_trop_long_est_tronque(
        self, session, config: WatcherConfig
    ) -> None:
        recorder = Recorder()
        publisher = TelegramPublisher(sender=recorder)
        await publisher.publish(session, "x" * 9000, config)
        assert len(recorder.messages[0]) <= 4000

    async def test_une_panne_d_envoi_ne_leve_jamais(
        self, session, config: WatcherConfig
    ) -> None:
        async def casse(text: str) -> int:
            raise RuntimeError("reseau coupe")

        publisher = TelegramPublisher(sender=casse)
        result = await publisher.publish(session, "message", config)
        assert result.sent is False
        assert "reseau coupe" in (result.reason or "")


# ---------------------------------------------------------------------------
# Cycle de vie (CDC3 sections 31 et 32)
# ---------------------------------------------------------------------------
class TestCycleDeVie:
    async def _suivre(
        self, session, signal: WatcherSignal, candles: list[Candle], config: WatcherConfig
    ):
        recorder = Recorder()
        tracker = LifecycleTracker(TelegramPublisher(sender=recorder))
        await repository.add_signal(session, signal)
        report = await tracker.run_once(
            session, FakeCandleEngine(candles), config, now=BASE + timedelta(minutes=30)
        )
        return report, recorder

    async def test_objectif_atteint_est_enregistre_et_publie(
        self, session, config: WatcherConfig
    ) -> None:
        signal = make_signal()
        report, recorder = await self._suivre(
            session, signal, candles_reaching(high=102.5, low=99.5), config
        )
        assert report.updated == 1
        assert signal.status is WatcherStatus.TP1_HIT
        assert len(recorder.messages) == 1
        assert "TP1" in recorder.messages[0]

    async def test_stop_touche_ferme_le_signal(self, session, config: WatcherConfig) -> None:
        signal = make_signal()
        report, _ = await self._suivre(
            session, signal, candles_reaching(high=100.5, low=97.0), config
        )
        assert signal.status is WatcherStatus.SL_HIT
        assert signal.result_r == -1.0
        assert signal.closed_at is not None
        assert report.closed == 1

    async def test_stop_prime_sur_objectif_dans_la_meme_bougie(
        self, session, config: WatcherConfig
    ) -> None:
        """On ignore l'ordre reel : l'hypothese retenue est la plus prudente."""
        signal = make_signal()
        await self._suivre(session, signal, candles_reaching(high=107.0, low=97.0), config)
        assert signal.status is WatcherStatus.SL_HIT

    async def test_entree_en_attente_non_declenchee_est_invalidee(
        self, session, config: WatcherConfig
    ) -> None:
        signal = make_signal(entry_type=EntryType.STOP, status=WatcherStatus.CREATED)
        await self._suivre(session, signal, candles_reaching(high=99.0, low=97.0), config)
        assert signal.status is WatcherStatus.INVALIDATED
        assert signal.result_r is None, "un signal jamais declenche n'a pas de resultat"

    async def test_entree_en_attente_declenchee_devient_active(
        self, session, config: WatcherConfig
    ) -> None:
        signal = make_signal(entry_type=EntryType.STOP, status=WatcherStatus.CREATED)
        await self._suivre(session, signal, candles_reaching(high=100.5, low=99.5), config)
        assert signal.status is WatcherStatus.ACTIVE

    async def test_signal_expire_quand_sa_duree_est_ecoulee(
        self, session, config: WatcherConfig
    ) -> None:
        signal = make_signal(expires_at=BASE + timedelta(minutes=10))
        recorder = Recorder()
        tracker = LifecycleTracker(TelegramPublisher(sender=recorder))
        await repository.add_signal(session, signal)
        await tracker.run_once(
            session, FakeCandleEngine([]), config, now=BASE + timedelta(hours=1)
        )
        assert signal.status is WatcherStatus.EXPIRED

    async def test_expiration_en_position_chiffre_la_sortie(
        self, session, config: WatcherConfig
    ) -> None:
        """Une position encore ouverte vaut son dernier cours, pas rien.

        Sans cela le message d'expiration ne dit ni a quel prix le signal se
        termine ni ce qu'il rapporte, et la position est comptee comme si elle
        n'avait jamais existe.
        """
        signal = make_signal(expires_at=BASE + timedelta(minutes=10))
        recorder = Recorder()
        tracker = LifecycleTracker(TelegramPublisher(sender=recorder))
        await repository.add_signal(session, signal)
        derniere = [
            Candle(
                time=BASE + timedelta(minutes=1),
                open=100.0,
                high=101.0,
                low=99.5,
                close=101.0,
                tick_volume=10,
            )
        ]
        await tracker.run_once(
            session, FakeCandleEngine(derniere), config, now=BASE + timedelta(hours=1)
        )
        assert signal.status is WatcherStatus.EXPIRED
        assert signal.result_r == pytest.approx(0.5)
        assert "101.00" in recorder.messages[-1]

    async def test_expiration_sans_declenchement_reste_sans_resultat(
        self, session, config: WatcherConfig
    ) -> None:
        """Une entree jamais touchee n'est pas une operation (docstring du module)."""
        signal = make_signal(
            entry_type=EntryType.STOP,
            status=WatcherStatus.CREATED,
            expires_at=BASE + timedelta(minutes=10),
        )
        recorder = Recorder()
        tracker = LifecycleTracker(TelegramPublisher(sender=recorder))
        await repository.add_signal(session, signal)
        await tracker.run_once(
            session,
            FakeCandleEngine(candles_reaching(high=99.5, low=98.5)),
            config,
            now=BASE + timedelta(hours=1),
        )
        assert signal.status is WatcherStatus.EXPIRED
        assert signal.result_r is None

    async def test_excursion_maximale_est_mesuree(
        self, session, config: WatcherConfig
    ) -> None:
        signal = make_signal()
        await self._suivre(session, signal, candles_reaching(high=101.0, low=99.0), config)
        assert signal.max_favorable_r == pytest.approx(0.5)
        assert signal.max_adverse_r == pytest.approx(0.5)

    async def test_les_mises_a_jour_peuvent_etre_coupees(
        self, session, config: WatcherConfig
    ) -> None:
        config.send_signal_updates = False
        signal = make_signal()
        _, recorder = await self._suivre(
            session, signal, candles_reaching(high=102.5, low=99.5), config
        )
        assert signal.status is WatcherStatus.TP1_HIT
        assert recorder.messages == [], "aucun message quand les mises a jour sont coupees"

    async def test_un_signal_clos_n_est_plus_suivi(
        self, session, config: WatcherConfig
    ) -> None:
        signal = make_signal(status=WatcherStatus.SL_HIT)
        report, _ = await self._suivre(
            session, signal, candles_reaching(high=110.0, low=99.0), config
        )
        assert report.checked == 0

    async def test_evenements_horodates_dans_l_ordre(
        self, session, config: WatcherConfig
    ) -> None:
        signal = make_signal()
        await self._suivre(session, signal, candles_reaching(high=102.5, low=99.5), config)
        assert signal.id is not None
        events = await repository.events_for(session, signal.id)
        assert next(event.kind for event in events) is WatcherStatus.TP1_HIT
