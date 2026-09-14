"""Acces aux signaux, a leurs evenements et aux messages Telegram."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import utcnow
from app.models.enums import Direction, SignalStatus
from app.models.telegram import TelegramMessage
from app.models.trading import Signal, SignalEvent


def build_idempotency_key(
    channel_id: int | None, message_id: int | None, content_hash: str | None = None
) -> str:
    """Cle unique d'un message : un meme message ne produit jamais deux ordres.

    Une reconnexion Telegram qui redistribue le meme message retombe sur la
    meme cle et le pipeline s'arrete immediatement (CDC section 26).
    """
    if channel_id is not None and message_id is not None:
        raw = f"tg:{channel_id}:{message_id}"
    elif content_hash:
        raw = f"content:{channel_id or 0}:{content_hash}"
    else:
        raw = f"manual:{utcnow().timestamp()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


async def find_by_idempotency_key(session: AsyncSession, key: str) -> Signal | None:
    result = await session.exec(select(Signal).where(Signal.idempotency_key == key))
    return result.first()


async def create(session: AsyncSession, signal: Signal) -> Signal:
    session.add(signal)
    await session.flush()
    return signal


async def get(session: AsyncSession, signal_id: int) -> Signal | None:
    return await session.get(Signal, signal_id)


async def save(session: AsyncSession, signal: Signal) -> Signal:
    signal.updated_at = utcnow()
    session.add(signal)
    await session.flush()
    return signal


async def set_status(
    session: AsyncSession,
    signal: Signal,
    status: SignalStatus,
    stage: str,
    message: str = "",
    success: bool = True,
    data: dict[str, Any] | None = None,
) -> Signal:
    """Change l'etat du signal et conserve la transition pour l'audit."""
    signal.status = status
    signal.updated_at = utcnow()
    session.add(signal)
    session.add(
        SignalEvent(
            signal_id=signal.id,
            stage=stage,
            status=status,
            success=success,
            message=message,
            data=data,
        )
    )
    await session.flush()
    return signal


async def add_event(
    session: AsyncSession,
    signal_id: int,
    stage: str,
    message: str = "",
    success: bool = True,
    status: SignalStatus | None = None,
    data: dict[str, Any] | None = None,
) -> SignalEvent:
    event = SignalEvent(
        signal_id=signal_id, stage=stage, message=message, success=success, status=status, data=data
    )
    session.add(event)
    await session.flush()
    return event


async def events_for(session: AsyncSession, signal_id: int) -> list[SignalEvent]:
    result = await session.exec(
        select(SignalEvent).where(SignalEvent.signal_id == signal_id).order_by(SignalEvent.created_at)
    )
    return list(result.all())


async def list_signals(
    session: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    channel_id: int | None = None,
    symbol: str | None = None,
    direction: Direction | None = None,
    statuses: list[SignalStatus] | None = None,
    since: datetime | None = None,
    include_follow_ups: bool = False,
) -> list[Signal]:
    statement = select(Signal)
    if not include_follow_ups:
        # Un message de suivi -- « TP1 atteint », « stop a break even »,
        # « TARGET COMPLETE 30+ PIPS » -- est un evenement du signal parent,
        # pas un signal. Sa ligne ne porte ni entree, ni stop, ni objectif :
        # affichee, elle donnait une carte vide « XAUUSD SELL / -- / -- / -- »
        # au milieu des vrais signaux. Elle reste en base, rattachee a son
        # parent, dont elle pilote la gestion ; elle ne remonte plus seule.
        statement = statement.where(Signal.original_signal_id == None)  # noqa: E711
    if channel_id is not None:
        statement = statement.where(Signal.channel_id == channel_id)
    if symbol:
        statement = statement.where(Signal.normalized_symbol == symbol.upper())
    if direction is not None:
        statement = statement.where(Signal.direction == direction)
    if statuses:
        statement = statement.where(Signal.status.in_(statuses))  # type: ignore[attr-defined]
    if since is not None:
        statement = statement.where(Signal.received_at >= since)
    statement = statement.order_by(Signal.received_at.desc()).offset(offset).limit(limit)
    result = await session.exec(statement)
    return list(result.all())


async def follow_ups_for(session: AsyncSession, signal_id: int, limit: int = 20) -> list[Signal]:
    """Messages de suivi rattaches a ce signal, du plus ancien au plus recent.

    La fiche du signal les listait en prenant les vingt derniers signaux tous
    canaux confondus puis en gardant ceux dont le parent correspondait : un
    suivi plus vieux que ces vingt lignes disparaissait de la fiche.
    """
    statement = (
        select(Signal)
        .where(Signal.original_signal_id == signal_id)
        .order_by(Signal.received_at)
        .limit(limit)
    )
    result = await session.exec(statement)
    return list(result.all())


async def count_signals(session: AsyncSession, since: datetime | None = None) -> int:
    statement = select(func.count()).select_from(Signal)
    if since is not None:
        statement = statement.where(Signal.received_at >= since)
    result = await session.exec(statement)
    return int(result.one())


async def count_duplicate_messages(session: AsyncSession) -> int:
    """Nombre de messages Telegram ayant produit plus d'un signal.

    La cle d'idempotence rend ce cas impossible en fonctionnement normal :
    un resultat different de zero signale une anomalie a investiguer avant
    d'envisager le mode reel (CDC section 68).
    """
    statement = (
        select(Signal.channel_id, Signal.telegram_message_id)
        .where(Signal.channel_id != None, Signal.telegram_message_id != None)  # noqa: E711
        .group_by(Signal.channel_id, Signal.telegram_message_id)
        .having(func.count() > 1)
    )
    result = await session.exec(statement)
    return len(list(result.all()))


async def find_recent_similar(
    session: AsyncSession,
    channel_id: int | None,
    symbol: str | None,
    direction: Direction | None,
    within_minutes: int = 30,
) -> Signal | None:
    """Detecte un signal identique republie peu apres (doublon fonctionnel)."""
    if symbol is None or direction is None:
        return None
    threshold = utcnow() - timedelta(minutes=within_minutes)
    statement = (
        select(Signal)
        .where(
            Signal.normalized_symbol == symbol.upper(),
            Signal.direction == direction,
            Signal.received_at >= threshold,
        )
        .order_by(Signal.received_at.desc())
    )
    if channel_id is not None:
        statement = statement.where(Signal.channel_id == channel_id)
    result = await session.exec(statement)
    return result.first()


async def find_parent_signal(
    session: AsyncSession,
    channel_id: int | None,
    reply_to_message_id: int | None,
    symbol: str | None,
    within_hours: int = 48,
) -> Signal | None:
    """Rattache un message de suivi au signal d'origine.

    Ordre de recherche (CDC section 18) : reponse Telegram explicite, puis
    dernier signal actif du meme canal sur le meme instrument, puis dernier
    signal actif du canal si le message ne cite aucun instrument.
    """
    active = [
        SignalStatus.SENT,
        SignalStatus.OPEN,
        SignalStatus.PARTIALLY_CLOSED,
        SignalStatus.MODIFIED,
        SignalStatus.APPROVED,
        SignalStatus.ORDER_CHECKED,
        SignalStatus.OBSERVED,
    ]
    threshold = utcnow() - timedelta(hours=within_hours)

    if reply_to_message_id is not None and channel_id is not None:
        result = await session.exec(
            select(Signal).where(
                Signal.channel_id == channel_id,
                Signal.telegram_message_id == reply_to_message_id,
            )
        )
        parent = result.first()
        if parent is not None:
            return parent

    statement = (
        select(Signal)
        .where(
            Signal.status.in_(active),  # type: ignore[attr-defined]
            Signal.received_at >= threshold,
        )
        .order_by(Signal.received_at.desc())
    )
    if channel_id is not None:
        statement = statement.where(Signal.channel_id == channel_id)
    if symbol:
        statement = statement.where(Signal.normalized_symbol == symbol.upper())

    result = await session.exec(statement)
    candidates = list(result.all())
    if not candidates:
        return None
    if symbol is None and len(candidates) > 1:
        # Message ambigu sans instrument et plusieurs signaux actifs :
        # on refuse de choisir plutot que d'agir sur la mauvaise position.
        return None
    return candidates[0]


# ---------------------------------------------------------------------------
# Messages Telegram
# ---------------------------------------------------------------------------

async def store_message(
    session: AsyncSession,
    channel_id: int,
    message_id: int,
    text: str,
    message_date: datetime,
    reply_to_message_id: int | None = None,
    is_historical: bool = False,
) -> tuple[TelegramMessage, bool]:
    """Enregistre un message. Retourne (message, cree) : False si deja connu."""
    result = await session.exec(
        select(TelegramMessage).where(
            TelegramMessage.channel_id == channel_id, TelegramMessage.message_id == message_id
        )
    )
    existing = result.first()
    if existing is not None:
        return existing, False

    message = TelegramMessage(
        channel_id=channel_id,
        message_id=message_id,
        text=text,
        message_date=message_date,
        reply_to_message_id=reply_to_message_id,
        is_historical=is_historical,
    )
    session.add(message)
    await session.flush()
    return message, True


async def mark_message_processed(session: AsyncSession, message: TelegramMessage) -> None:
    message.processed = True
    session.add(message)
    await session.flush()


async def list_messages(
    session: AsyncSession, channel_id: int, limit: int = 200, offset: int = 0
) -> list[TelegramMessage]:
    result = await session.exec(
        select(TelegramMessage)
        .where(TelegramMessage.channel_id == channel_id)
        .order_by(TelegramMessage.message_date.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.all())
