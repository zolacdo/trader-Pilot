"""Le cycle de vie d'une position doit se raconter, sur les deux canaux.

Les gabarits ``take_profit_hit``, ``stop_loss_hit`` et ``position_closed``
existaient depuis longtemps dans ``notifications/templates.py`` -- et aucun
n'etait appele nulle part. Une position pouvait s'ouvrir, franchir ses
objectifs et se fermer sans qu'un seul message ne parte.

Trois exigences ici, dans cet ordre d'importance :

1. aucune annonce ne peut faire echouer une operation de trading ;
2. les objectifs sont annonces palier par palier, jusqu'au dernier ;
3. les deux canaux -- telephone et Telegram -- recoivent le meme evenement, et
   la panne de l'un n'empeche pas l'autre.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Direction
from app.services.trading import announcements


class Espion:
    """Retient ce qui part, sans rien envoyer."""

    def __init__(self) -> None:
        self.pousses: list[Any] = []
        self.telegrams: list[str] = []

    async def pousse(self, session: AsyncSession, draft: Any) -> bool:
        self.pousses.append(draft)
        return True

    async def telegram(self, session: AsyncSession, texte: str) -> bool:
        self.telegrams.append(texte)
        return True


@pytest.fixture
def espion(monkeypatch: pytest.MonkeyPatch) -> Espion:
    mouchard = Espion()
    monkeypatch.setattr(announcements, "_pousse", mouchard.pousse)
    monkeypatch.setattr(announcements, "_telegram", mouchard.telegram)
    return mouchard


class TestDeuxCanaux:
    async def test_un_objectif_part_sur_les_deux_canaux(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        await announcements.objectif_atteint(
            session,
            symbol="XAUUSD",
            direction=Direction.BUY,
            level=2,
            total=3,
            price=2410.0,
            profit=12.5,
        )

        assert len(espion.pousses) == 1
        assert len(espion.telegrams) == 1

    async def test_le_compte_des_objectifs_figure_dans_les_deux(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        """« TP2 sur 3 » est ce qui permet de suivre sans ouvrir l'application."""
        await announcements.objectif_atteint(
            session, symbol="XAUUSD", direction=Direction.BUY, level=2, total=3
        )

        assert "TP2/3" in espion.pousses[0].title
        assert "TP2/3" in espion.telegrams[0]
        assert "Reste 1 objectif" in espion.telegrams[0]

    async def test_le_dernier_objectif_annonce_la_fin_du_suivi(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        await announcements.objectif_atteint(
            session, symbol="XAUUSD", direction=Direction.BUY, level=3, total=3
        )

        assert "Tous les objectifs sont validés" in espion.telegrams[0]

    async def test_une_panne_telegram_laisse_partir_la_notification(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un canal muet ne doit pas rendre l'autre muet."""
        pousses: list[Any] = []

        async def pousse_ok(session: AsyncSession, draft: Any) -> bool:
            pousses.append(draft)
            return True

        async def telegram_en_panne(session: AsyncSession, texte: str) -> bool:
            raise RuntimeError("canal injoignable")

        monkeypatch.setattr(announcements, "_pousse", pousse_ok)
        monkeypatch.setattr(announcements, "_telegram", telegram_en_panne)

        with pytest.raises(RuntimeError):
            # La protection vit dans _telegram lui-meme : ici on verifie
            # seulement que la notification est partie AVANT l'echec.
            await announcements.objectif_atteint(
                session, symbol="XAUUSD", direction=Direction.BUY, level=1, total=2
            )

        assert len(pousses) == 1


class TestOrdresEnAttente:
    async def test_un_ordre_depose_est_annonce(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        """Le cas qui passait totalement inapercu."""
        await announcements.ordre_en_attente(
            session,
            symbol="BTCUSD",
            direction=Direction.BUY,
            order_type="BUY_LIMIT",
            entry=77000.0,
            stop_loss=76500.0,
            take_profits=[77500.0, 78000.0],
        )

        texte = espion.telegrams[0]
        assert "ORDRE EN ATTENTE" in texte
        assert "BUY LIMIT" in texte
        assert "77000.00" in texte
        assert "n'est ouverte tant que ce prix" in texte

    async def test_un_ordre_declenche_est_annonce(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        await announcements.ordre_declenche(
            session, symbol="BTCUSD", direction=Direction.BUY, price=77000.0, volume=0.02
        )

        assert "ORDRE DÉCLENCHÉ" in espion.telegrams[0]

    async def test_un_ordre_jamais_touche_est_annonce(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        """Sans ce message, on croit qu'une position dort quelque part."""
        await announcements.ordre_non_declenche(
            session, symbol="BTCUSD", direction=Direction.BUY, entry=77000.0
        )

        texte = espion.telegrams[0]
        assert "NON DÉCLENCHÉ" in texte
        assert "aucune position n'a été ouverte" in texte


class TestFermeture:
    async def test_une_perte_est_annoncee_comme_un_stop(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        await announcements.position_fermee(
            session,
            symbol="XAUUSD",
            direction=Direction.BUY,
            atteints=0,
            total=3,
            profit=-7.2,
        )

        assert "STOP LOSS" in espion.telegrams[0]
        assert "STOP LOSS" in espion.pousses[0].title

    async def test_un_gain_est_annonce_comme_une_fermeture(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        await announcements.position_fermee(
            session,
            symbol="XAUUSD",
            direction=Direction.BUY,
            atteints=3,
            total=3,
            profit=18.4,
        )

        assert "POSITION FERMÉE" in espion.telegrams[0]

    async def test_le_bilan_des_objectifs_clot_le_suivi(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        """Une position partie a 2 TP sur 3 ne doit pas sembler courir encore."""
        await announcements.position_fermee(
            session,
            symbol="XAUUSD",
            direction=Direction.BUY,
            atteints=2,
            total=3,
            profit=9.0,
        )

        assert "2/3 objectif(s) validé(s)" in espion.telegrams[0]
        assert "2/3 objectif(s) validé(s)" in espion.pousses[0].body

    async def test_sans_objectif_declare_le_bilan_le_dit(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        await announcements.position_fermee(
            session, symbol="XAUUSD", direction=Direction.BUY, atteints=0, total=0, profit=1.0
        )

        assert "aucun objectif déclaré" in espion.telegrams[0]


class TestRobustesse:
    async def test_une_panne_de_notification_ne_leve_pas(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le trading ne doit jamais echouer parce qu'un message n'est pas parti."""

        class ServiceEnPanne:
            async def send(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("service de notification indisponible")

        monkeypatch.setattr(announcements, "notification_service", ServiceEnPanne())

        assert await announcements._pousse(session, _draft()) is False

    async def test_un_texte_telegram_echappe_le_html(
        self, session: AsyncSession, espion: Espion
    ) -> None:
        """Un symbole exotique ne doit pas casser le message."""
        await announcements.ordre_non_declenche(
            session,
            symbol="A<b>B",
            direction=Direction.SELL,
            entry=1.0,
            reason="motif <script>",
        )

        texte = espion.telegrams[0]
        assert "<script>" not in texte
        assert "&lt;script&gt;" in texte


def _draft() -> Any:
    from app.models.intelligence import NotificationCategory, NotificationPriority
    from app.services.notifications.formatting import NotificationDraft

    return NotificationDraft(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        title="titre",
        body="corps",
    )
