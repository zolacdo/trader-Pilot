"""Un message de suivi ne s'affiche pas comme un signal.

« TARGET COMPLETE 30+ PIPS DONE », « TP1 atteint », « stop a break even » :
ces messages pilotent la gestion d'une position deja ouverte. Ils sont
enregistres comme lignes rattachees a leur signal parent -- c'est par elles que
le moteur ferme partiellement ou remonte le stop -- mais ils ne portent ni
entree, ni stop, ni objectif.

Le 14/09/2026, la liste des signaux affichait ainsi des cartes vides :
« XAUUSD SELL -- Interprete -- ENTREE --  SL --  TP -- » au milieu des vrais
signaux. La ligne doit rester en base et sortir de la liste.
"""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import Direction, FollowUpAction, ParserSource, SignalStatus
from app.models.telegram import Channel
from app.models.trading import Signal
from app.repositories import signal_repo


@pytest.fixture
async def canal(session: AsyncSession) -> Channel:
    channel = Channel(telegram_id=-100123, title="Canal de test", monitored=True)
    session.add(channel)
    await session.flush()
    return channel


async def _signal(session: AsyncSession, canal: Channel, message_id: int) -> Signal:
    signal = Signal(
        channel_id=canal.id,
        telegram_message_id=message_id,
        idempotency_key=f"parent-{message_id}",
        raw_text="XAUUSD BUY 3320\nSL 3310\nTP 3340",
        symbol="XAUUSD",
        normalized_symbol="XAUUSD",
        direction=Direction.BUY,
        entry_price=3320.0,
        stop_loss=3310.0,
        take_profits=[3340.0],
        parser_source=ParserSource.DETERMINISTIC,
        status=SignalStatus.PARSED,
    )
    await signal_repo.create(session, signal)
    return signal


async def _suivi(
    session: AsyncSession, canal: Channel, parent: Signal, message_id: int
) -> Signal:
    suivi = Signal(
        channel_id=canal.id,
        telegram_message_id=message_id,
        idempotency_key=f"suivi-{message_id}",
        raw_text="XAUUSD TARGET COMPLETE 30+ PIPS DONE",
        symbol="XAUUSD",
        normalized_symbol="XAUUSD",
        direction=Direction.BUY,
        parser_source=ParserSource.DETERMINISTIC,
        status=SignalStatus.PARSED,
        original_signal_id=parent.id,
        follow_up_action=FollowUpAction.TP_HIT,
    )
    await signal_repo.create(session, suivi)
    return suivi


class TestListeDesSignaux:
    async def test_un_suivi_ne_remonte_pas_dans_la_liste(
        self, session: AsyncSession, canal: Channel
    ) -> None:
        parent = await _signal(session, canal, 1)
        await _suivi(session, canal, parent, 2)

        lignes = await signal_repo.list_signals(session, limit=50)

        assert [s.id for s in lignes] == [parent.id]

    async def test_le_suivi_reste_en_base(
        self, session: AsyncSession, canal: Channel
    ) -> None:
        """Masque a l'ecran, jamais perdu : le moteur s'en sert."""
        parent = await _signal(session, canal, 1)
        suivi = await _suivi(session, canal, parent, 2)

        lignes = await signal_repo.list_signals(session, limit=50, include_follow_ups=True)

        assert {s.id for s in lignes} == {parent.id, suivi.id}

    async def test_la_fiche_du_parent_liste_ses_suivis(
        self, session: AsyncSession, canal: Channel
    ) -> None:
        """Et ils restent consultables la ou ils ont un sens."""
        parent = await _signal(session, canal, 1)
        premier = await _suivi(session, canal, parent, 2)
        second = await _suivi(session, canal, parent, 3)

        suivis = await signal_repo.follow_ups_for(session, parent.id)

        assert [s.id for s in suivis] == [premier.id, second.id]

    async def test_les_suivis_d_un_autre_signal_ne_s_y_melent_pas(
        self, session: AsyncSession, canal: Channel
    ) -> None:
        premier_parent = await _signal(session, canal, 1)
        second_parent = await _signal(session, canal, 10)
        sien = await _suivi(session, canal, premier_parent, 2)
        await _suivi(session, canal, second_parent, 11)

        suivis = await signal_repo.follow_ups_for(session, premier_parent.id)

        assert [s.id for s in suivis] == [sien.id]
