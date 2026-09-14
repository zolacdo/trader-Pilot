"""Le rattrapage : relire l'historique quand le flux n'a rien rendu.

Le flux d'updates Telegram n'est pas un contrat de livraison. Mesure faite le
12/09/2026 sur le canal de test : les messages 2 a 5, tapes depuis Telegram
Desktop, ont tous ete captes ; les messages 6 a 16, publies par la session du
Bridge elle-meme, aucun. Quatre sur quatre contre zero sur onze.

Le champ ``last_seen_message_id`` existait deja en base -- il etait ecrit a
chaque message recu, et relu par personne. Cette suite couvre la relecture qui
s'en sert enfin, et ses deux precautions : ne pas analyser tout un historique
au premier passage, et ne pas rejouer un signal perime.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.models.telegram import Channel, TelegramMessage
from app.services.telegram.listener import ChannelListener

TELEGRAM_ID = -1004344665828


class FauxMessage:
    """Message Telethon minimal : juste ce que le listener lit."""

    def __init__(self, identifiant: int, texte: str, date: datetime | None = None) -> None:
        self.id = identifiant
        self.message = texte
        self.date = date or utcnow()
        self.reply_to = None
        self.edit_date = None


class FauxClient:
    """Client Telethon remplace : il rend l'historique qu'on lui a donne."""

    def __init__(self, messages: list[FauxMessage]) -> None:
        self._messages = messages
        self.appels: list[dict[str, Any]] = []

    async def get_messages(self, entity: int, limit: int = 30) -> list[FauxMessage]:
        self.appels.append({"entity": entity, "limit": limit})
        # Telethon rend l'historique du plus recent au plus ancien.
        return sorted(self._messages, key=lambda m: m.id, reverse=True)[:limit]


class FauxService:
    def __init__(self, client: FauxClient | None) -> None:
        self.client = client

    def require_client(self) -> Any:
        return self.client


async def _canal(session: AsyncSession, dernier_vu: int | None) -> Channel:
    canal = Channel(
        telegram_id=TELEGRAM_ID,
        title="Canal de test",
        monitored=True,
        last_seen_message_id=dernier_vu,
    )
    session.add(canal)
    await session.flush()
    return canal


def _listener(
    client: FauxClient | None,
) -> tuple[ChannelListener, list[tuple[int, dict[str, Any]]]]:
    recus: list[tuple[int, dict[str, Any]]] = []

    async def rappel(channel_id: int, payload: dict[str, Any]) -> None:
        recus.append((channel_id, payload))

    return ChannelListener(FauxService(client), rappel), recus


class TestAmorcage:
    async def test_le_premier_passage_n_analyse_aucun_historique(
        self, session: AsyncSession
    ) -> None:
        """Activer un canal ne doit pas declencher l'analyse de tout son passe."""
        await _canal(session, dernier_vu=None)
        client = FauxClient([FauxMessage(i, f"BUY XAUUSD {i}") for i in (10, 11, 12)])
        listener, recus = _listener(client)

        rattrapes = await listener.catch_up()

        assert rattrapes == 0
        assert recus == [], "l'historique a ete analyse au premier passage"

    async def test_le_premier_passage_pose_le_curseur(self, session: AsyncSession) -> None:
        """Sinon le passage suivant recommencerait a zero, indefiniment."""
        canal = await _canal(session, dernier_vu=None)
        client = FauxClient([FauxMessage(i, f"texte {i}") for i in (10, 11, 12)])
        listener, _ = _listener(client)

        await listener.catch_up()

        await session.refresh(canal)
        assert canal.last_seen_message_id == 12


class TestRattrapage:
    async def test_les_messages_manques_sont_analyses(self, session: AsyncSession) -> None:
        """Le coeur du correctif : ce que le flux n'a pas rendu est recupere."""
        await _canal(session, dernier_vu=10)
        client = FauxClient([FauxMessage(i, f"BUY XAUUSD {i}") for i in (10, 11, 12)])
        listener, recus = _listener(client)

        rattrapes = await listener.catch_up()

        assert rattrapes == 2
        assert [payload["messageId"] for _, payload in recus] == [11, 12]

    async def test_l_ordre_chronologique_est_respecte(self, session: AsyncSession) -> None:
        """Un message de suivi doit arriver apres le signal qu'il modifie."""
        await _canal(session, dernier_vu=5)
        client = FauxClient([FauxMessage(i, f"message {i}") for i in (9, 7, 8, 6)])
        listener, recus = _listener(client)

        await listener.catch_up()

        assert [payload["messageId"] for _, payload in recus] == [6, 7, 8, 9]

    async def test_un_message_deja_connu_n_est_pas_rejoue(self, session: AsyncSession) -> None:
        """L'ecoute et le rattrapage se croisent : jamais deux fois le meme."""
        canal = await _canal(session, dernier_vu=10)
        session.add(
            TelegramMessage(
                channel_id=canal.id,
                message_id=11,
                text="BUY XAUUSD 11",
                message_date=utcnow(),
                processed=True,
            )
        )
        await session.flush()
        client = FauxClient(
            [FauxMessage(11, "BUY XAUUSD 11"), FauxMessage(12, "BUY XAUUSD 12")]
        )
        listener, recus = _listener(client)

        await listener.catch_up()

        assert [payload["messageId"] for _, payload in recus] == [12]

    async def test_les_messages_vides_sont_ignores(self, session: AsyncSession) -> None:
        await _canal(session, dernier_vu=10)
        client = FauxClient([FauxMessage(11, "   "), FauxMessage(12, "BUY XAUUSD")])
        listener, recus = _listener(client)

        await listener.catch_up()

        assert [payload["messageId"] for _, payload in recus] == [12]


class TestSignalPerime:
    async def test_un_message_trop_ancien_n_est_pas_rejoue(self, session: AsyncSession) -> None:
        """Rejouer un signal de la veille ouvrirait une position hors sujet."""
        await _canal(session, dernier_vu=10)
        client = FauxClient([FauxMessage(11, "BUY XAUUSD", date=utcnow() - timedelta(hours=6))])
        listener, recus = _listener(client)

        rattrapes = await listener.catch_up()

        assert rattrapes == 1, "le message doit rester enregistre"
        assert recus == [], "un signal de six heures a ete envoye au pipeline"

    async def test_un_message_recent_est_bien_rejoue(self, session: AsyncSession) -> None:
        await _canal(session, dernier_vu=10)
        client = FauxClient(
            [FauxMessage(11, "BUY XAUUSD", date=utcnow() - timedelta(minutes=2))]
        )
        listener, recus = _listener(client)

        await listener.catch_up()

        assert [payload["messageId"] for _, payload in recus] == [11]


class TestRobustesse:
    async def test_sans_client_telegram_le_rattrapage_ne_leve_pas(
        self, session: AsyncSession
    ) -> None:
        listener, recus = _listener(None)

        assert await listener.catch_up() == 0
        assert recus == []

    async def test_un_canal_en_erreur_n_empeche_pas_les_autres(
        self, session: AsyncSession
    ) -> None:
        """Un canal supprime cote Telegram ne doit pas faire taire le reste."""
        await _canal(session, dernier_vu=10)

        class ClientEnPanne(FauxClient):
            async def get_messages(self, entity: int, limit: int = 30) -> list[FauxMessage]:
                raise RuntimeError("canal introuvable")

        listener, recus = _listener(ClientEnPanne([]))

        assert await listener.catch_up() == 0
        assert recus == []

    async def test_un_canal_non_surveille_est_ignore(self, session: AsyncSession) -> None:
        canal = Channel(
            telegram_id=TELEGRAM_ID,
            title="Canal desactive",
            monitored=False,
            last_seen_message_id=10,
        )
        session.add(canal)
        await session.flush()
        client = FauxClient([FauxMessage(11, "BUY XAUUSD")])
        listener, recus = _listener(client)

        assert await listener.catch_up() == 0
        assert client.appels == [], "un canal desactive a ete interroge"
        assert recus == []


async def test_la_date_du_message_est_conservee(session: AsyncSession) -> None:
    """Le RiskManager refuse un signal trop ancien : encore faut-il la date."""
    await _canal(session, dernier_vu=10)
    client = FauxClient([FauxMessage(11, "BUY XAUUSD", date=utcnow())])
    listener, recus = _listener(client)

    await listener.catch_up()

    assert recus[0][1]["date"] is not None
