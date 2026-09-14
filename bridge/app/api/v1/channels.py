"""Routes des canaux surveilles : ajout, reglages, analyse, comparaison."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.database.session import get_session
from app.models.core import Device
from app.models.enums import ChannelMode
from app.models.telegram import Channel, ChannelAnalysis, ChannelSettings
from app.repositories import channel_repo, signal_repo
from app.schemas.requests import ChannelAddRequest, ChannelAnalyzeRequest, ChannelSettingsRequest
from app.services import journal
from app.services.security.auth import require_device
from app.services.telegram import fetch_history, join_channel, resolve_channel, telegram_service

logger = get_logger(__name__)

router = APIRouter(prefix="/channels", tags=["canaux"])


def _channel_payload(
    channel: Channel,
    settings: ChannelSettings | None,
    tally: tuple[int, Any] | None = None,
) -> dict[str, Any]:
    """Etat d'un canal. ``tally`` porte le compte reel des signaux.

    Sans lui on retombe sur le compteur memorise, qui sous-compte : il ignore
    les signaux refuses.
    """
    nombre, dernier_signal = tally if tally else (channel.signals_count, channel.last_signal_at)
    return {
        "id": channel.id,
        "telegramId": channel.telegram_id,
        "username": channel.username,
        "title": channel.title,
        "description": channel.description,
        "membersCount": channel.members_count,
        "isPublic": channel.is_public,
        "joined": channel.joined,
        "monitored": channel.monitored,
        "signalsCount": nombre,
        "lastMessageAt": channel.last_message_at.isoformat() if channel.last_message_at else None,
        "lastSignalAt": dernier_signal.isoformat() if dernier_signal else None,
        "settings": _settings_payload(settings),
    }


def _settings_payload(settings: ChannelSettings | None) -> dict[str, Any] | None:
    if settings is None:
        return None
    return {
        "enabled": settings.enabled,
        "mode": settings.mode.value,
        "copyBuy": settings.copy_buy,
        "copySell": settings.copy_sell,
        "riskPercent": settings.risk_percent,
        "maxPositions": settings.max_positions,
        "maxLot": settings.max_lot,
        "maxSpreadPoints": settings.max_spread_points,
        "maxSignalAgeSeconds": settings.max_signal_age_seconds,
        "minConfidence": settings.min_confidence,
        "requireStopLoss": settings.require_stop_loss,
        "requireTakeProfit": settings.require_take_profit,
        "multiTpStrategy": settings.multi_tp_strategy.value if settings.multi_tp_strategy else None,
        "allowedSymbols": list(settings.allowed_symbols or []),
    }


def _analysis_payload(analysis: ChannelAnalysis) -> dict[str, Any]:
    return {
        "id": analysis.id,
        "channelId": analysis.channel_id,
        "createdAt": analysis.created_at.isoformat(),
        "messagesScanned": analysis.messages_scanned,
        "signalLikeMessages": analysis.signal_like_messages,
        "parsedMessages": analysis.parsed_messages,
        "followUpMessages": analysis.follow_up_messages,
        "closeMessages": analysis.close_messages,
        "modifyMessages": analysis.modify_messages,
        "duplicateSignals": analysis.duplicate_signals,
        "structureQuality": analysis.structure_quality,
        "withStopLossRate": analysis.with_stop_loss_rate,
        "withTakeProfitRate": analysis.with_take_profit_rate,
        "parseableRate": analysis.parseable_rate,
        "averageTakeProfits": analysis.average_take_profits,
        "signalsPerDay": analysis.signals_per_day,
        "firstMessageAt": analysis.first_message_at.isoformat() if analysis.first_message_at else None,
        "lastMessageAt": analysis.last_message_at.isoformat() if analysis.last_message_at else None,
        "symbols": analysis.symbols,
        "directions": analysis.directions,
        "backtest": analysis.backtest,
        "notes": analysis.notes,
        "disclaimer": (
            "Mesures factuelles observees sur les messages analyses. "
            "Elles ne predisent aucune performance future."
        ),
    }


@router.get("")
async def list_channels(
    monitored_only: bool = Query(default=False, alias="monitoredOnly"),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    channels = await channel_repo.list_channels(session, monitored_only=monitored_only)
    tallies = await channel_repo.signal_tallies(session)
    payload = []
    for channel in channels:
        settings = await channel_repo.get_settings(session, channel.id)
        payload.append(_channel_payload(channel, settings, tallies.get(channel.id)))
    return payload


@router.post("", status_code=201)
async def add_channel(
    payload: ChannelAddRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Ajoute un canal a la surveillance. Il demarre TOUJOURS en mode OBSERVE."""
    # Le nom d'utilisateur passe en premier : Telethon ne conserve pas son cache
    # d'entites d'une session a l'autre, donc resoudre un canal public par son
    # identifiant numerique echoue apres un redemarrage du Bridge, alors que le
    # nom reste toujours resolvable.
    reference: Any = payload.username or payload.telegram_id
    if not reference:
        raise HTTPException(status_code=400, detail="Fournissez un identifiant ou un nom d'utilisateur")

    try:
        info = await resolve_channel(telegram_service, reference)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Telegram : {exc}") from exc
    if info is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Canal introuvable ou inaccessible depuis votre compte Telegram. "
                "Relancez la recherche, ou ouvrez le canal une fois dans Telegram."
            ),
        )

    if payload.join and not info.get("alreadyJoined"):
        # Rejoindre est une action explicite de l'utilisateur, jamais automatique.
        try:
            await join_channel(telegram_service, info["id"])
            info["alreadyJoined"] = True
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Impossible de rejoindre : {exc}") from exc

    channel = await channel_repo.upsert(
        session,
        telegram_id=int(info["id"]),
        title=info.get("title") or "",
        username=info.get("username"),
        description=info.get("description"),
        members_count=info.get("membersCount"),
        is_public=bool(info.get("isPublic", True)),
        joined=bool(info.get("alreadyJoined")),
    )
    channel.monitored = True
    session.add(channel)
    settings = await channel_repo.get_settings(session, channel.id)
    if settings is not None and settings.mode is None:
        settings.mode = ChannelMode.OBSERVE
        session.add(settings)

    await journal.record(
        session,
        event="channel_added",
        message=f"Canal ajoute a la surveillance en mode observation : {channel.title}",
        category="channel",
        channel_id=channel.id,
    )
    await _refresh_listener(session)
    return _channel_payload(channel, settings)


@router.get("/{channel_id}")
async def get_channel(
    channel_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    channel = await channel_repo.get(session, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal inconnu")
    settings = await channel_repo.get_settings(session, channel_id)
    profile = await channel_repo.get_profile(session, channel_id)
    analysis = await channel_repo.latest_analysis(session, channel_id)
    signals = await signal_repo.list_signals(session, limit=20, channel_id=channel_id)
    return {
        **_channel_payload(channel, settings),
        "parserProfile": {
            "knownFormats": list(profile.known_formats or []),
            "lastSuccessfulFormat": profile.last_successful_format,
            "deterministicSuccess": profile.deterministic_success,
            "aiFallbackCount": profile.ai_fallback_count,
            "confidence": profile.confidence,
            "symbolAliases": dict(profile.symbol_aliases or {}),
        },
        "latestAnalysis": _analysis_payload(analysis) if analysis else None,
        "recentSignals": [
            {
                "id": signal.id,
                "symbol": signal.normalized_symbol,
                "direction": signal.direction.value if signal.direction else None,
                "status": signal.status.value,
                "confidence": signal.confidence,
                "receivedAt": signal.received_at.isoformat(),
            }
            for signal in signals
        ],
    }


@router.patch("/{channel_id}/settings")
async def update_channel_settings(
    channel_id: int,
    payload: ChannelSettingsRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    channel = await channel_repo.get(session, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal inconnu")

    changes = payload.model_dump(exclude_unset=True, by_alias=False)
    settings = await channel_repo.update_settings(session, channel_id, changes)

    if "mode" in changes and settings is not None:
        await journal.record(
            session,
            event="channel_mode_changed",
            message=f"{channel.title} passe en mode {settings.mode.value}",
            category="channel",
            channel_id=channel_id,
        )
        await journal.audit(
            session,
            action="channel_mode_changed",
            actor="user",
            target=channel.title,
            details={"mode": settings.mode.value},
        )
    return _settings_payload(settings) or {}


@router.post("/{channel_id}/monitor")
async def set_monitoring(
    channel_id: int,
    enabled: bool = Query(default=True),
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    channel = await channel_repo.set_monitored(session, channel_id, enabled)
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal inconnu")
    await _refresh_listener(session)
    settings = await channel_repo.get_settings(session, channel_id)
    return _channel_payload(channel, settings)


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        deleted = await channel_repo.delete_channel(session, channel_id)
    except channel_repo.ChannelHasHistory as exc:
        # Supprimer romprait le lien entre un trade et son canal d'origine.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ce canal a deja produit {exc.trades} position(s) : le supprimer "
                "romprait l'historique des trades. Desactivez plutot sa surveillance."
            ),
        ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Canal inconnu")
    await _refresh_listener(session)
    return {"deleted": True}


@router.post("/{channel_id}/analyze")
async def analyze_channel(
    channel_id: int,
    payload: ChannelAnalyzeRequest,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Analyse les N derniers messages accessibles du canal (CDC section 13)."""
    channel = await channel_repo.get(session, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal inconnu")

    try:
        # Meme raison que pour l'ajout : le nom d'utilisateur reste resolvable
        # apres un redemarrage, l'identifiant numerique non.
        reference = channel.username or channel.telegram_id
        messages = await fetch_history(telegram_service, reference, payload.messages)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Historique indisponible : {exc}") from exc
    if not messages:
        raise HTTPException(status_code=422, detail="Aucun message accessible dans ce canal")

    # Import differe : le Bridge doit demarrer meme si le module d'analyse
    # est absent ou en cours de mise a jour.
    from app.services.channels.analyzer import analyze_channel as run_analysis
    from app.services.trading.engine import trading_engine

    analysis = await run_analysis(
        session,
        channel,
        messages,
        run_backtest=payload.backtest,
        market=trading_engine.market,
    )
    await journal.record(
        session,
        event="channel_analyzed",
        message=f"{channel.title} : {analysis.messages_scanned} messages analyses",
        category="channel",
        channel_id=channel_id,
    )
    return _analysis_payload(analysis)


@router.get("/{channel_id}/analyses")
async def list_analyses(
    channel_id: int,
    _: Device = Depends(require_device),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    analyses = await channel_repo.list_analyses(session, channel_id)
    return [_analysis_payload(analysis) for analysis in analyses]


@router.get("/compare/table")
async def compare_channels(
    _: Device = Depends(require_device), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Tableau de comparaison (CDC section 72). Aucun classement n'est impose."""
    from app.services.statistics.service import compare_channels as build_comparison

    rows = await build_comparison(session)
    return {
        "rows": rows,
        "disclaimer": (
            "Donnees observees uniquement. L'application ne designe pas de meilleur canal : "
            "les resultats passes ne predisent pas les resultats futurs."
        ),
    }


async def _refresh_listener(session: AsyncSession | None = None) -> None:
    """Recharge la liste des canaux ecoutes apres modification.

    La transaction en cours est validee d'abord. Le rechargement ouvre sa
    PROPRE session : sans ce commit, il ne verrait pas le canal qui vient
    d'etre ajoute et rechargerait la liste d'avant — le nouveau canal n'etait
    alors ecoute qu'au redemarrage suivant.
    """
    from app.services.telegram_runtime import channel_listener

    if session is not None:
        try:
            await session.commit()
        except Exception as exc:
            logger.warning("Validation avant rechargement de l'ecoute impossible : %s", exc)
            return

    if channel_listener is not None:
        try:
            await channel_listener.refresh_subscriptions()
        except Exception as exc:  # l'echec de rafraichissement ne doit pas casser l'API
            logger.warning("Rafraichissement de l'ecoute Telegram impossible : %s", exc)
