"""Le signal produit par le watcher doit reellement devenir une position.

Le watcher publiait son signal dans un canal Telegram et s'arretait la, en
comptant sur l'ecoute pour le lui renvoyer. Telegram ne rejoue pas dans le
flux d'updates les messages qu'une session a elle-meme envoyes : le signal
partait sans jamais revenir, et aucun ordre n'etait passe.

Mesure faite sur le canal de test : les messages 2 a 5, tapes depuis Telegram
Desktop, ont tous ete captes ; les messages 6 a 16, publies par le Bridge,
aucun. Quatre sur quatre contre zero sur onze.

Cette suite verifie le raccourci qui remplace ce detour, et surtout ses trois
garde-fous : aucun ordre reel ne doit partir d'un test (CDC3 section 61), donc
le moteur de trading est toujours remplace par un espion.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trading.engine import ProcessOutcome
from app.watcher import execution
from app.watcher.config import WatcherConfig

TEXTE = "BUY XAUUSD\nEntry 2400.00\nSL 2390.00\nTP1 2420.00"


class MoteurEspion:
    """Remplace le moteur de trading : il note l'appel, il n'ordonne rien."""

    def __init__(self, outcome: ProcessOutcome | None = None) -> None:
        self.appels: list[dict[str, Any]] = []
        self._outcome = outcome or ProcessOutcome(stage="executed", executed=True, signal_id=42)

    async def handle_message(self, session: AsyncSession, **kwargs: Any) -> ProcessOutcome:
        self.appels.append(kwargs)
        return self._outcome


@pytest.fixture
def espion(monkeypatch: pytest.MonkeyPatch) -> MoteurEspion:
    moteur = MoteurEspion()
    monkeypatch.setattr(execution, "trading_engine", moteur)
    return moteur


class TestGardeFous:
    """Trois situations doivent laisser le broker parfaitement tranquille."""

    async def test_auto_trade_desactive_n_appelle_pas_le_moteur(
        self, session: AsyncSession, espion: MoteurEspion
    ) -> None:
        config = WatcherConfig(auto_trade=False)

        rapport = await execution.execute_signal(session, TEXTE, config)

        assert rapport.attempted is False
        assert rapport.executed is False
        assert espion.appels == [], "le moteur a ete appele malgre auto_trade=False"

    async def test_le_mode_analyse_seule_n_appelle_pas_le_moteur(
        self, session: AsyncSession, espion: MoteurEspion
    ) -> None:
        """dry_run interdit deja la publication : il doit interdire l'ordre."""
        config = WatcherConfig(auto_trade=True, dry_run=True)

        rapport = await execution.execute_signal(session, TEXTE, config)

        assert rapport.attempted is False
        assert espion.appels == [], "un ordre est parti en mode analyse seule"

    async def test_un_texte_vide_n_appelle_pas_le_moteur(
        self, session: AsyncSession, espion: MoteurEspion
    ) -> None:
        config = WatcherConfig(auto_trade=True)

        rapport = await execution.execute_signal(session, "   \n  ", config)

        assert rapport.attempted is False
        assert espion.appels == []


class TestTransmission:
    async def test_le_signal_est_remis_au_moteur_mot_pour_mot(
        self, session: AsyncSession, espion: MoteurEspion
    ) -> None:
        """Le moteur doit voir exactement ce que voit le lecteur du canal."""
        config = WatcherConfig(auto_trade=True)

        rapport = await execution.execute_signal(session, TEXTE, config, message_id=77)

        assert rapport.executed is True
        assert rapport.signal_id == 42
        assert len(espion.appels) == 1
        assert espion.appels[0]["text"] == TEXTE

    async def test_l_identifiant_du_message_sert_de_cle_d_idempotence(
        self, session: AsyncSession, espion: MoteurEspion
    ) -> None:
        """Sans lui, une capture tardive par l'ecoute ouvrirait une 2e position."""
        config = WatcherConfig(auto_trade=True)

        await execution.execute_signal(session, TEXTE, config, message_id=77)

        assert espion.appels[0]["message_id"] == 77

    async def test_un_signal_non_publie_est_quand_meme_execute(
        self, session: AsyncSession, espion: MoteurEspion
    ) -> None:
        """Un canal injoignable ne doit pas faire rater la position."""
        config = WatcherConfig(auto_trade=True)

        rapport = await execution.execute_signal(session, TEXTE, config, message_id=None)

        assert rapport.executed is True
        assert espion.appels[0]["message_id"] is None

    async def test_un_refus_du_moteur_n_est_pas_une_erreur(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le RiskManager a le droit de refuser : le watcher doit l'accepter."""
        refus = ProcessOutcome(stage="rejected", executed=False, detail="Risque trop eleve")
        monkeypatch.setattr(execution, "trading_engine", MoteurEspion(refus))

        rapport = await execution.execute_signal(session, TEXTE, WatcherConfig(auto_trade=True))

        assert rapport.attempted is True
        assert rapport.executed is False
        assert rapport.detail == "Risque trop eleve"


class TestRobustesse:
    async def test_une_panne_du_moteur_ne_casse_pas_l_analyse(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sinon un broker indisponible ferait perdre le signal enregistre."""

        class MoteurEnPanne:
            async def handle_message(self, *args: Any, **kwargs: Any) -> ProcessOutcome:
                raise RuntimeError("terminal MetaTrader injoignable")

        monkeypatch.setattr(execution, "trading_engine", MoteurEnPanne())

        rapport = await execution.execute_signal(session, TEXTE, WatcherConfig(auto_trade=True))

        assert rapport.stage == "error"
        assert rapport.executed is False
        assert "MetaTrader" in rapport.detail


# ---------------------------------------------------------------------------
# Le moteur du watcher branche reellement l’execution
# ---------------------------------------------------------------------------
class Recorder:
    """Fonction d’envoi injectee : elle garde les textes, elle n’envoie rien."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, text: str) -> int:
        self.messages.append(text)
        return len(self.messages)


class TestChaineComplete:
    async def test_un_signal_publie_part_aussi_vers_le_moteur(
        self, session: AsyncSession, espion: MoteurEspion, geometrie_permissive: None
    ) -> None:
        """C’est le raccourci qui manquait : publier ET transmettre.

        La garde geometrique est desserree parce que ce test mesure la CHAINE,
        pas la forme des niveaux. Les bougies du simulateur ne dependent que du
        symbole et de l'horodatage ABSOLU : selon l'heure a laquelle la suite
        tourne, le stop calcule tenait dans 4 ATR ou non, et le test passait le
        matin pour echouer l'apres-midi. Constate le 16/09/2026 : « Stop trop
        large (5.4 ATR) » sur un scenario inchange depuis des jours.
        """
        from app.services.market_data.engine import MarketDataEngine
        from app.services.mt5.fake_service import FakeMetaTraderService
        from app.watcher.engine import WatcherEngine
        from app.watcher.publisher import TelegramPublisher

        service = FakeMetaTraderService(balance=10000.0)
        await service.initialize()
        market = MarketDataEngine(service)
        recorder = Recorder()
        watcher = WatcherEngine(TelegramPublisher(sender=recorder))

        config = WatcherConfig()
        config.ai_enabled = False
        config.send_startup_message = False
        config.minimum_score = 1.0
        config.minimum_rr = 0.1
        config.auto_trade = True

        outcome = await watcher.analyse(session, market, "XAUUSD", "XAUUSD", config)

        assert outcome.decision.is_tradable, outcome.detail
        assert outcome.execution is not None
        assert outcome.execution.attempted is True
        assert len(espion.appels) == 1

        # Le moteur recoit les MEMES NIVEAUX que le lecteur, pas le meme texte.
        # Exiger un texte identique etait un piege : le format detaille annote
        # chaque objectif de son rapport de risque — « TP1 : 1.34474  (1:1.0) »
        # — et le parseur lisait les deux nombres. Le 14/09/2026, un GBPUSD
        # SELL est arrive avec les objectifs [3.0, 2.0, 1.34474, 1.34169,
        # 1.33865, 1.0] et a ete refuse pour « TP1 doit etre sous l'entree ».
        # Ce qui compte est l'identite des niveaux, pas celle de la mise en page.
        from app.services.signals import deterministic_parser, validator

        signal = outcome.signal
        assert signal is not None
        lu = deterministic_parser.parse(espion.appels[0]["text"])
        assert lu.symbol == signal.symbol
        assert lu.direction is signal.direction
        entree = lu.entry_price if lu.entry_price is not None else lu.entry_min
        assert entree == pytest.approx(signal.entry)
        assert lu.stop_loss == pytest.approx(signal.stop_loss)
        assert lu.take_profits == pytest.approx(signal.targets)
        assert validator.validate(validator.sanitize(lu)).ok, (
            "le texte transmis au moteur doit passer le validateur"
        )

    async def test_le_pied_de_page_dit_la_verite_en_mode_reel(self) -> None:
        """Annoncer que rien n’est passe serait faux, et grave."""
        from app.watcher.formatter import detailed_signal
        from tests.test_watcher_publication import make_signal

        signal = make_signal()
        analyse = detailed_signal(signal, auto_trade=False).lower()
        reel = detailed_signal(signal, auto_trade=True).lower()
        assert "aucun ordre n" in analyse
        assert "aucun ordre n" not in reel
        assert "transmis au broker" in reel
