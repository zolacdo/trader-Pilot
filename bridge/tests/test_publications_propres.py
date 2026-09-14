"""Le Bridge ne rejoue jamais ce qu'il publie — mais il exécute ce qu'il décide.

Le canal de publication fait partie des canaux surveilles. Les annonces de
trade portent un ordre complet — symbole, sens, entree, stop, objectifs — et
le parseur les lisait donc comme des signaux valides.

Mesure du 14/09/2026 : un seul vrai signal XAUUSD de PARAMOUR (#136) a produit
quatre ordres identiques a 4310. Chaque execution publiait une annonce
« ORDRE EN ATTENTE », relue au tour suivant comme un nouveau signal, qui
declenchait une execution, qui publiait une annonce.

Ces tests verrouillent les DEUX faces, qui arrivent par la meme porte :

* un message relu depuis Telegram -> ignore ;
* le meme message remis directement par le watcher -> execute.

Confondre les deux casserait l'un ou l'autre : soit la boucle revient, soit le
watcher ne prend plus jamais position.
"""

from __future__ import annotations

import pytest

from app.models.telegram import Channel, PublishedMessage
from app.services.signals import pipeline

CHAT_ID = -1004344665828
MESSAGE_ID = 229

# L'annonce reelle qui a produit les doublons, texte d'origine.
ANNONCE_ORDRE = (
    "⏳ ORDRE EN ATTENTE — XAUUSDm\n\n"
    "ACHAT · BUY LIMIT\n"
    "Entrée attendue : 4310.00\n"
    "SL : 4304.00\n"
    "TP : 4318.00 / 4321.00 / 4323.00\n\n"
    "Aucune position n'est encore ouverte."
)


@pytest.fixture
async def canal(session) -> Channel:
    canal = Channel(telegram_id=CHAT_ID, title="Tradepilot test", monitored=True)
    session.add(canal)
    await session.flush()
    return canal


@pytest.fixture
async def publication(session) -> PublishedMessage:
    """Un message que le Bridge a lui-meme publie."""
    trace = PublishedMessage(chat_id=CHAT_ID, message_id=MESSAGE_ID)
    session.add(trace)
    await session.flush()
    return trace


class TestRelectureDepuisTelegram:
    async def test_notre_propre_annonce_est_ignoree(
        self, session, canal: Channel, publication: PublishedMessage
    ) -> None:
        """Le cas exact des doublons du 14/09/2026."""
        resultat = await pipeline.process_message(
            session, ANNONCE_ORDRE, channel=canal, message_id=MESSAGE_ID, allow_ai=False
        )
        assert resultat.action == "ignored"
        assert resultat.signal is None
        assert "publie par le Bridge" in resultat.detail

    async def test_l_annonce_porte_pourtant_un_ordre_complet(self) -> None:
        """C'est bien pour cela que le tri par contenu ne suffisait pas."""
        from app.services.signals import deterministic_parser

        parsed = deterministic_parser.parse(ANNONCE_ORDRE)
        assert pipeline.has_minimum_order_content(parsed) is True

    async def test_un_message_non_publie_par_nous_passe(
        self, session, canal: Channel, publication: PublishedMessage
    ) -> None:
        """Seul l'identifiant enregistre est ecarte, pas le canal entier."""
        resultat = await pipeline.process_message(
            session,
            "BUY XAUUSD\nEntry 4310.00\nSL 4304.00\nTP1 4318.00",
            channel=canal,
            message_id=MESSAGE_ID + 1,
            allow_ai=False,
        )
        assert resultat.action != "ignored"

    async def test_un_autre_canal_n_est_pas_concerne(self, session) -> None:
        """Le registre est indexe par conversation, pas seulement par message."""
        session.add(PublishedMessage(chat_id=CHAT_ID, message_id=MESSAGE_ID))
        autre = Channel(telegram_id=-1001921434298, title="PARAMOUR", monitored=True)
        session.add(autre)
        await session.flush()

        resultat = await pipeline.process_message(
            session,
            "SELL XAUUSD\nEntry 4338.00\nSL 4349.00\nTP1 4335.00",
            channel=autre,
            message_id=MESSAGE_ID,
            allow_ai=False,
        )
        assert resultat.action != "ignored"


class TestRemiseDirecte:
    async def test_le_watcher_execute_ce_qu_il_vient_de_publier(
        self, session, canal: Channel, publication: PublishedMessage
    ) -> None:
        """La regression que le registre a failli introduire.

        Le watcher publie son signal PUIS le transmet au moteur avec le meme
        identifiant de message. Sans ``internal_handoff``, le registre — dont
        c'est justement le role d'ecarter cet identifiant — refuserait
        l'execution que le watcher vient de demander, et plus aucune position
        ne s'ouvrirait.
        """
        resultat = await pipeline.process_message(
            session,
            "BUY XAUUSD\nEntry 4310.00\nSL 4304.00\nTP1 4318.00",
            channel=canal,
            message_id=MESSAGE_ID,
            allow_ai=False,
            internal_handoff=True,
        )
        assert resultat.action != "ignored"
        assert resultat.parsed is not None
        assert resultat.parsed.symbol == "XAUUSD"

    async def test_le_drapeau_est_faux_par_defaut(self) -> None:
        """La securite doit etre l'etat par defaut, jamais une option a cocher."""
        import inspect

        signature = inspect.signature(pipeline.process_message)
        assert signature.parameters["internal_handoff"].default is False

    async def test_le_watcher_positionne_bien_le_drapeau(self) -> None:
        """Verrouille le cablage : un refactor ne doit pas le perdre."""
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "app" / "watcher" / "execution.py"
        assert "internal_handoff=True" in source.read_text(encoding="utf-8")


class TestRegistre:
    async def test_une_publication_est_enregistree(self, session) -> None:
        from app.watcher.config import WatcherConfig
        from app.watcher.publisher import TelegramPublisher

        envoyes: list[str] = []

        async def enregistreur(texte: str) -> int:
            envoyes.append(texte)
            return 4242

        publisher = TelegramPublisher(sender=enregistreur)
        config = WatcherConfig()
        resultat = await publisher.publish(session, "message de test", config)

        assert resultat.sent is True
        assert resultat.message_id == 4242
        from sqlmodel import select

        trace = (
            await session.exec(
                select(PublishedMessage).where(PublishedMessage.message_id == 4242)
            )
        ).first()
        assert trace is not None

    async def test_le_mode_dry_run_n_enregistre_rien(self, session) -> None:
        from sqlmodel import select

        from app.watcher.config import WatcherConfig
        from app.watcher.publisher import TelegramPublisher

        async def enregistreur(texte: str) -> int:
            return 5555

        config = WatcherConfig()
        config.dry_run = True
        publisher = TelegramPublisher(sender=enregistreur)
        await publisher.publish(session, "message de test", config)

        trace = (
            await session.exec(
                select(PublishedMessage).where(PublishedMessage.message_id == 5555)
            )
        ).first()
        assert trace is None
