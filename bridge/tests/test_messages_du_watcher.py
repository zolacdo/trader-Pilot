"""Les messages d'information du Market Watcher ne sont pas des signaux.

Le canal de publication du watcher fait partie des canaux surveilles : le
Bridge relit donc ce que le watcher vient d'ecrire. Sur huit sortes de
messages, une seule est un ordre. Les sept autres portent un instrument et un
mot de direction, et arrivaient dans la liste des signaux avec entree, stop et
objectifs vides, refuses pour « confiance insuffisante ».

Les textes utilises ici sont produits par le vrai formateur du watcher, pas
recopies a la main : si quelqu'un reformule un message, ces tests suivent.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.enums import Direction
from app.models.telegram import Channel
from app.repositories import settings_repo
from app.services.signals import pipeline
from app.watcher import formatter
from app.watcher.models import EntryType, WatcherDecision, WatcherSignal, WatcherStatus

WATCHER_TG_ID = -1004344665828
EXTERNE_TG_ID = -1001921434298


@pytest.fixture
async def canal_watcher(session) -> Channel:
    """Le canal de publication du watcher, declare comme surveille."""
    await settings_repo.set_setting(
        session, pipeline.SETTING_WATCHER_CHANNEL, WATCHER_TG_ID
    )
    canal = Channel(telegram_id=WATCHER_TG_ID, title="Tradepilot test", monitored=True)
    session.add(canal)
    await session.flush()
    return canal


@pytest.fixture
async def canal_externe(session) -> Channel:
    canal = Channel(
        telegram_id=EXTERNE_TG_ID, title="PARAMOUR FOREX TRADER VIP SIGNALS", monitored=True
    )
    session.add(canal)
    await session.flush()
    return canal


def signal_du_watcher() -> WatcherSignal:
    """Vrai signal : instrument, sens, entree, stop et objectifs."""
    return WatcherSignal(
        symbol="ETHUSD",
        broker_symbol="ETHUSDm",
        direction=Direction.BUY,
        decision=WatcherDecision.BUY,
        status=WatcherStatus.CONFIRMED,
        timeframe="M15",
        entry_type=EntryType.MARKET,
        entry=2532.24,
        stop_loss=2527.19,
        digits=2,
        take_profit_1=2536.19,
        take_profit_2=2542.83,
        take_profit_3=2547.39,
        risk_distance=5.05,
        risk_reward_1=0.78,
        risk_reward_2=2.1,
        risk_reward_3=3.0,
        score=72.1,
        confidence=72,
        created_at=datetime(2026, 9, 12, 10, 31, tzinfo=UTC),
    )


def messages_d_information() -> dict[str, str]:
    """Les sept messages du watcher qui ne sont PAS des ordres."""
    return {
        "sous_surveillance": formatter.watch_message(
            symbol="ETHUSD",
            current_price=2524.02,
            score=67.0,
            buy_trigger=2526.95,
            sell_trigger=None,
            digits=2,
            detail="Structure : sequence contraction, BOS aligne",
            direction=Direction.BUY,
        ),
        "surveillance_levee": formatter.watch_closed_message(
            symbol="US30",
            direction=Direction.SELL,
            trigger=52554.7,
            current_price=52557.1,
            digits=2,
            reason="WAIT (score 54.1/100) — Score 54.1 sous le minimum exige (70.0).",
        ),
        "surveillance_confirmee": formatter.watch_confirmed_message(
            symbol="BTCUSD",
            direction=Direction.BUY,
            trigger=77665.26,
            current_price=77680.0,
            digits=2,
        ),
        "cycle_de_vie": formatter.lifecycle_message(
            signal_du_watcher(), WatcherStatus.TP1_HIT, 2536.19, "Objectif TP1 atteint."
        ),
        "alerte_economique": formatter.news_alert_message(
            title="US CPI",
            currency="USD",
            impact="CRITICAL",
            scheduled_at=datetime(2026, 9, 15, 12, 30, tzinfo=UTC),
            affected=["XAUUSD", "EURUSD"],
        ),
        "actualite_majeure": formatter.breaking_news_message(
            headline="La Fed releve ses taux de facon inattendue",
            source="Reuters",
            impact="HIGH",
            sentiment="BEARISH",
            affected=["XAUUSD", "US30"],
        ),
        "demarrage": formatter.startup_message(
            symbols=["BTCUSD", "ETHUSD"], dry_run=False, version="market_watcher_v1.0"
        ),
    }


# ---------------------------------------------------------------------------
# Le critere : contenu minimal d'un ordre
# ---------------------------------------------------------------------------
class TestContenuMinimal:
    @pytest.mark.parametrize("nom", sorted(messages_d_information()))
    def test_aucun_message_d_information_ne_porte_un_ordre(self, nom: str) -> None:
        from app.services.signals import deterministic_parser

        texte = messages_d_information()[nom]
        parsed = deterministic_parser.parse(texte)
        assert pipeline.has_minimum_order_content(parsed) is False, nom

    @pytest.mark.parametrize("simple", [False, True])
    def test_un_vrai_signal_porte_bien_un_ordre(self, simple: bool) -> None:
        """Le critere doit laisser passer les deux formats du watcher."""
        from app.services.signals import deterministic_parser

        texte = formatter.signal_message(signal_du_watcher(), simple=simple)
        parsed = deterministic_parser.parse(texte)
        assert pipeline.has_minimum_order_content(parsed) is True


# ---------------------------------------------------------------------------
# Le pipeline
# ---------------------------------------------------------------------------
class TestPipeline:
    @pytest.mark.parametrize("nom", sorted(messages_d_information()))
    async def test_les_messages_d_information_sont_ecartes(
        self, session, canal_watcher: Channel, nom: str
    ) -> None:
        texte = messages_d_information()[nom]
        resultat = await pipeline.process_message(
            session, texte, channel=canal_watcher, message_id=1, allow_ai=False
        )
        assert resultat.action == "ignored", nom
        assert resultat.signal is None

    async def test_aucune_ligne_n_est_creee_en_base(
        self, session, canal_watcher: Channel
    ) -> None:
        """Le symptome visible : des cartes vides dans la liste des signaux."""
        from app.repositories import signal_repo

        avant = len(await signal_repo.list_signals(session, limit=200))
        for index, texte in enumerate(messages_d_information().values()):
            await pipeline.process_message(
                session, texte, channel=canal_watcher, message_id=100 + index, allow_ai=False
            )
        apres = len(await signal_repo.list_signals(session, limit=200))
        assert apres == avant

    async def test_un_vrai_signal_du_watcher_passe_toujours(
        self, session, canal_watcher: Channel
    ) -> None:
        texte = formatter.signal_message(signal_du_watcher(), simple=False)
        resultat = await pipeline.process_message(
            session, texte, channel=canal_watcher, message_id=2, allow_ai=False
        )
        assert resultat.action != "ignored"
        assert resultat.parsed is not None
        assert resultat.parsed.symbol == "ETHUSD"
        assert resultat.parsed.direction is Direction.BUY

    async def test_le_format_simple_passe_aussi(
        self, session, canal_watcher: Channel
    ) -> None:
        texte = formatter.signal_message(signal_du_watcher(), simple=True)
        resultat = await pipeline.process_message(
            session, texte, channel=canal_watcher, message_id=3, allow_ai=False
        )
        assert resultat.action != "ignored"

    async def test_le_tp1_du_watcher_ne_se_rattache_a_rien(
        self, session, canal_watcher: Channel
    ) -> None:
        """Sinon il fermerait partiellement une position ouverte ailleurs."""
        texte = messages_d_information()["cycle_de_vie"]
        resultat = await pipeline.process_message(
            session, texte, channel=canal_watcher, message_id=4, allow_ai=False
        )
        assert resultat.action == "ignored"
        assert resultat.parent_signal is None


# ---------------------------------------------------------------------------
# Les canaux externes ne changent pas de comportement
# ---------------------------------------------------------------------------
class TestCanauxExternes:
    async def test_un_canal_externe_n_est_pas_filtre(
        self, session, canal_watcher: Channel, canal_externe: Channel
    ) -> None:
        """Le tri ne vaut QUE pour le canal de publication du watcher."""
        texte = messages_d_information()["sous_surveillance"]
        resultat = await pipeline.process_message(
            session, texte, channel=canal_externe, message_id=5, allow_ai=False
        )
        assert resultat.detail != (
            "Message d'information du Market Watcher : aucun ordre exploitable"
        )

    async def test_un_vrai_signal_externe_reste_traite(
        self, session, canal_externe: Channel
    ) -> None:
        texte = "SELL XAUUSD\nEntry 4338.00\nSL 4349.00\nTP1 4335.00\nTP2 4332.00"
        resultat = await pipeline.process_message(
            session, texte, channel=canal_externe, message_id=6, allow_ai=False
        )
        assert resultat.action != "ignored"
        assert resultat.parsed is not None
        assert resultat.parsed.symbol == "XAUUSD"

    async def test_sans_canal_le_filtre_ne_s_applique_pas(self, session) -> None:
        """L'analyse manuelle d'un texte ne passe par aucun canal."""
        texte = messages_d_information()["sous_surveillance"]
        resultat = await pipeline.process_message(
            session, texte, channel=None, message_id=7, allow_ai=False
        )
        assert resultat.detail != (
            "Message d'information du Market Watcher : aucun ordre exploitable"
        )


# ---------------------------------------------------------------------------
# Robustesse
# ---------------------------------------------------------------------------
class TestRobustesse:
    async def test_sans_reglage_de_canal_rien_n_est_filtre(
        self, session, canal_externe: Channel
    ) -> None:
        """Aucun canal watcher declare : le pipeline garde son comportement."""
        texte = messages_d_information()["sous_surveillance"]
        resultat = await pipeline.process_message(
            session, texte, channel=canal_externe, message_id=8, allow_ai=False
        )
        assert resultat.detail != (
            "Message d'information du Market Watcher : aucun ordre exploitable"
        )

    def test_un_ordre_sans_stop_n_est_pas_complet(self) -> None:
        from app.services.signals import deterministic_parser

        parsed = deterministic_parser.parse("BUY ETHUSD\nEntry 2532.24\nTP1 2536.19")
        assert pipeline.has_minimum_order_content(parsed) is False

    def test_un_ordre_sans_entree_n_est_pas_complet(self) -> None:
        from app.services.signals import deterministic_parser

        parsed = deterministic_parser.parse("BUY ETHUSD\nSL 2527.19\nTP1 2536.19")
        assert pipeline.has_minimum_order_content(parsed) is False

    def test_une_fourchette_d_entree_suffit(self) -> None:
        """Beaucoup de canaux donnent une zone d'entree, pas un prix unique."""
        from app.services.signals import deterministic_parser

        parsed = deterministic_parser.parse(
            "BUY XAUUSD\nEntry 4330.00 - 4335.00\nSL 4320.00\nTP1 4350.00"
        )
        assert pipeline.has_minimum_order_content(parsed) is True
