"""Acces aux canaux, a leurs reglages, profils de parsing et analyses."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import utcnow
from app.models.enums import ChannelMode
from app.models.telegram import (
    Channel,
    ChannelAnalysis,
    ChannelParserProfile,
    ChannelSettings,
    TelegramMessage,
)
from app.models.trading import BacktestResult, Signal, SignalEvent, TradeRecord


async def get(session: AsyncSession, channel_id: int) -> Channel | None:
    return await session.get(Channel, channel_id)


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> Channel | None:
    result = await session.exec(select(Channel).where(Channel.telegram_id == telegram_id))
    return result.first()


async def list_channels(session: AsyncSession, monitored_only: bool = False) -> list[Channel]:
    statement = select(Channel)
    if monitored_only:
        statement = statement.where(Channel.monitored == True)
    statement = statement.order_by(Channel.title)
    result = await session.exec(statement)
    return list(result.all())


async def upsert(
    session: AsyncSession,
    telegram_id: int,
    title: str,
    username: str | None = None,
    description: str | None = None,
    members_count: int | None = None,
    is_public: bool = True,
    joined: bool = False,
) -> Channel:
    channel = await get_by_telegram_id(session, telegram_id)
    if channel is None:
        channel = Channel(telegram_id=telegram_id, title=title)
    channel.title = title or channel.title
    if username is not None:
        channel.username = username
    if description is not None:
        channel.description = description
    if members_count is not None:
        channel.members_count = members_count
    channel.is_public = is_public
    channel.joined = joined or channel.joined
    session.add(channel)
    await session.flush()
    await get_settings(session, channel.id)  # cree les reglages par defaut
    return channel


async def signal_tallies(session: AsyncSession) -> dict[int, tuple[int, Any]]:
    """Nombre de signaux et date du dernier, par canal.

    Compte TOUS les signaux enregistres, refuses compris : un canal dont les
    signaux sont systematiquement rejetes est une information, pas un vide.
    Une seule requete groupee, pour ne pas interroger la base par canal.
    """
    resultat = await session.exec(
        select(
            Signal.channel_id,
            func.count(Signal.id),
            func.max(Signal.received_at),
        )
        .where(Signal.channel_id != None)  # noqa: E711
        .group_by(Signal.channel_id)
    )
    return {
        int(channel_id): (int(nombre), dernier)
        for channel_id, nombre, dernier in resultat.all()
        if channel_id is not None
    }


async def get_settings(session: AsyncSession, channel_id: int | None) -> ChannelSettings | None:
    """Reglages du canal. Un nouveau canal demarre toujours en OBSERVE."""
    if channel_id is None:
        return None
    result = await session.exec(select(ChannelSettings).where(ChannelSettings.channel_id == channel_id))
    settings = result.first()
    if settings is None:
        # Ne jamais creer de reglages pour un canal absent : cela laisserait
        # une ligne orpheline que la contrainte de cle etrangere rejetterait.
        if await get(session, channel_id) is None:
            return None
        settings = ChannelSettings(channel_id=channel_id, mode=ChannelMode.OBSERVE)
        session.add(settings)
        await session.flush()
    return settings


async def update_settings(session: AsyncSession, channel_id: int, changes: dict) -> ChannelSettings | None:
    settings = await get_settings(session, channel_id)
    if settings is None:
        return None
    for key, value in changes.items():
        if key in {"id", "channel_id", "updated_at"}:
            continue
        if hasattr(settings, key):
            setattr(settings, key, value)
    settings.updated_at = utcnow()
    session.add(settings)
    await session.flush()
    return settings


async def set_monitored(session: AsyncSession, channel_id: int, monitored: bool) -> Channel | None:
    channel = await get(session, channel_id)
    if channel is None:
        return None
    channel.monitored = monitored
    session.add(channel)
    await session.flush()
    return channel


class ChannelHasHistory(Exception):
    """Le canal a deja produit des trades : sa suppression romprait l'audit."""

    def __init__(self, trades: int) -> None:
        self.trades = trades
        super().__init__(f"{trades} trade(s) rattache(s) a ce canal")


async def count_signals(session: AsyncSession, channel_id: int) -> int:
    result = await session.exec(
        select(func.count()).select_from(Signal).where(Signal.channel_id == channel_id)
    )
    return int(result.one())


async def count_trades(session: AsyncSession, channel_id: int) -> int:
    """Positions, simulees ou reelles, issues de ce canal."""
    result = await session.exec(
        select(func.count()).select_from(TradeRecord).where(TradeRecord.channel_id == channel_id)
    )
    return int(result.one())


async def delete_channel(session: AsyncSession, channel_id: int) -> bool:
    """Supprime un canal et tout ce qui en derive.

    Sont effaces : reglages, profil de parsing, analyses, simulations, messages
    bruts et signaux observes. Tout cela se recalcule a partir de Telegram.

    En revanche, un canal ayant reellement produit des positions n'est jamais
    supprime : chaque trade doit rester rattachable a son canal d'origine
    (CDC section 65). L'interrupteur de surveillance permet alors de cesser de
    l'ecouter sans perdre l'historique.
    """
    channel = await get(session, channel_id)
    if channel is None:
        return False

    trades = await count_trades(session, channel_id)
    if trades:
        raise ChannelHasHistory(trades)

    # Les evenements referencent les signaux : ils partent en premier.
    signal_ids = list(
        (await session.exec(select(Signal.id).where(Signal.channel_id == channel_id))).all()
    )
    if signal_ids:
        await session.exec(delete(SignalEvent).where(SignalEvent.signal_id.in_(signal_ids)))
        await session.exec(delete(Signal).where(Signal.channel_id == channel_id))

    # Les simulations referencent les analyses : elles partent en premier.
    analyses = await session.exec(
        select(ChannelAnalysis.id).where(ChannelAnalysis.channel_id == channel_id)
    )
    analysis_ids = list(analyses.all())
    if analysis_ids:
        await session.exec(
            delete(BacktestResult).where(BacktestResult.analysis_id.in_(analysis_ids))
        )

    for model in (ChannelAnalysis, ChannelParserProfile, TelegramMessage, ChannelSettings):
        await session.exec(delete(model).where(model.channel_id == channel_id))

    await session.delete(channel)
    await session.flush()
    return True


# ---------------------------------------------------------------------------
# Profils de parsing appris par canal
# ---------------------------------------------------------------------------

async def get_profile(session: AsyncSession, channel_id: int) -> ChannelParserProfile:
    result = await session.exec(
        select(ChannelParserProfile).where(ChannelParserProfile.channel_id == channel_id)
    )
    profile = result.first()
    if profile is None:
        profile = ChannelParserProfile(channel_id=channel_id)
        session.add(profile)
        await session.flush()
    return profile


async def record_parse_success(
    session: AsyncSession, channel_id: int, format_signature: str | None, used_ai: bool
) -> ChannelParserProfile:
    """Memorise le gabarit reconnu pour eviter un appel IA la prochaine fois."""
    profile = await get_profile(session, channel_id)
    if used_ai:
        profile.ai_fallback_count += 1
    else:
        profile.deterministic_success += 1
    if format_signature:
        formats = list(profile.known_formats or [])
        if format_signature not in formats:
            formats.append(format_signature)
            profile.known_formats = formats[-20:]
        profile.last_successful_format = format_signature
    total = profile.deterministic_success + profile.ai_fallback_count
    profile.confidence = round(profile.deterministic_success / total, 3) if total else 0.0
    profile.updated_at = utcnow()
    session.add(profile)
    await session.flush()
    return profile


async def add_symbol_alias(session: AsyncSession, channel_id: int, alias: str, canonical: str) -> None:
    profile = await get_profile(session, channel_id)
    aliases = dict(profile.symbol_aliases or {})
    aliases[alias.upper()] = canonical.upper()
    profile.symbol_aliases = aliases
    profile.updated_at = utcnow()
    session.add(profile)
    await session.flush()


async def channel_aliases(session: AsyncSession, channel_id: int | None) -> dict[str, str]:
    if channel_id is None:
        return {}
    profile = await get_profile(session, channel_id)
    return dict(profile.symbol_aliases or {})


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

async def save_analysis(session: AsyncSession, analysis: ChannelAnalysis) -> ChannelAnalysis:
    session.add(analysis)
    await session.flush()
    return analysis


async def latest_analysis(session: AsyncSession, channel_id: int) -> ChannelAnalysis | None:
    result = await session.exec(
        select(ChannelAnalysis)
        .where(ChannelAnalysis.channel_id == channel_id)
        .order_by(ChannelAnalysis.created_at.desc())
    )
    return result.first()


async def list_analyses(session: AsyncSession, channel_id: int, limit: int = 10) -> list[ChannelAnalysis]:
    result = await session.exec(
        select(ChannelAnalysis)
        .where(ChannelAnalysis.channel_id == channel_id)
        .order_by(ChannelAnalysis.created_at.desc())
        .limit(limit)
    )
    return list(result.all())
