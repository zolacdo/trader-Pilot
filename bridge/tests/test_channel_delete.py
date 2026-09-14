"""Suppression d'un canal : nettoyage des donnees derivees, audit preserve."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.models.enums import Direction
from app.models.telegram import ChannelAnalysis, ChannelParserProfile, TelegramMessage
from app.models.trading import BacktestResult, Signal, SignalEvent, TradeRecord
from app.repositories import channel_repo


async def _make_channel(session: AsyncSession, telegram_id: int = -100123) -> int:
    channel = await channel_repo.upsert(
        session, telegram_id=telegram_id, title="Canal d'essai", username="essai"
    )
    assert channel.id is not None
    return channel.id


async def test_suppression_nettoie_les_donnees_derivees(session: AsyncSession) -> None:
    """Regression : la suppression echouait sur une contrainte de cle etrangere."""
    channel_id = await _make_channel(session)

    analysis = ChannelAnalysis(channel_id=channel_id, messages_scanned=10)
    session.add(analysis)
    await session.flush()
    assert analysis.id is not None

    session.add(BacktestResult(analysis_id=analysis.id, channel_id=channel_id))
    session.add(ChannelParserProfile(channel_id=channel_id))
    session.add(
        TelegramMessage(
            channel_id=channel_id, message_id=1, text="BUY XAUUSD", message_date=utcnow()
        )
    )
    await session.flush()

    assert await channel_repo.delete_channel(session, channel_id) is True
    assert await channel_repo.get(session, channel_id) is None


async def test_canal_observe_reste_supprimable(session: AsyncSession) -> None:
    """Des signaux seulement observes ne doivent pas enfermer l'utilisateur."""
    channel_id = await _make_channel(session, telegram_id=-100456)

    signal = Signal(
        channel_id=channel_id,
        idempotency_key="essai-1",
        raw_text="BUY XAUUSD SL 3300 TP 3400",
    )
    session.add(signal)
    await session.flush()
    session.add(SignalEvent(signal_id=signal.id, stage="parser"))
    await session.flush()

    assert await channel_repo.delete_channel(session, channel_id) is True
    assert await channel_repo.get(session, channel_id) is None


async def test_canal_avec_positions_n_est_pas_supprime(session: AsyncSession) -> None:
    """Un trade doit rester rattachable a son canal d'origine (CDC section 65)."""
    channel_id = await _make_channel(session, telegram_id=-100789)

    session.add(
        TradeRecord(
            channel_id=channel_id,
            ticket=5001,
            symbol="XAUUSDm",
            direction=Direction.BUY,
        )
    )
    await session.flush()

    with pytest.raises(channel_repo.ChannelHasHistory) as erreur:
        await channel_repo.delete_channel(session, channel_id)

    assert erreur.value.trades == 1
    # Le canal est toujours la : seule la surveillance peut etre coupee.
    assert await channel_repo.get(session, channel_id) is not None


async def test_suppression_d_un_canal_inconnu_renvoie_faux(session: AsyncSession) -> None:
    assert await channel_repo.delete_channel(session, 99999) is False
