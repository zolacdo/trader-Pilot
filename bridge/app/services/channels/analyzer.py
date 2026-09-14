"""Channel Analyzer : mesures factuelles sur l'historique d'un canal (CDC section 13).

Le module ne va chercher aucun message lui-meme : la couche Telegram fournit
deja la liste des messages historiques. Chaque message est rejoue par le parser
deterministe **sans jamais appeler l'IA** (``allow_ai=False``) : analyser
plusieurs centaines de messages avec un modele gratuit consommerait la totalite
du quota disponible (CDC section 20).

Le rapport produit ne contient que des mesures observees. Aucune promesse de
gain, aucun jugement de valeur, aucune recommandation : l'utilisateur lit des
chiffres et decide seul (CDC section 13).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.enums import FollowUpAction
from app.models.telegram import Channel, ChannelAnalysis
from app.repositories import channel_repo
from app.services import journal
from app.services.channels import backtester
from app.services.events import EventType, event_bus
from app.services.mt5.interface import MetaTraderService
from app.services.signals import follow_up_parser, pipeline
from app.services.signals.models import ParsedSignal
from app.services.signals.normalizer import normalize_upper

logger = get_logger(__name__)

# Deux signaux identiques republies dans cette fenetre sont comptes comme un
# doublon fonctionnel (meme regle que le pipeline temps reel, CDC section 26).
DUPLICATE_WINDOW = timedelta(minutes=30)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Un message qui affiche une intention d'entree sans etre exploitable par le
# parser reste compte comme "ressemblant a un signal" : c'est precisement ce
# que mesure le taux de messages interpretables.
_TRADE_INTENT = re.compile(r"\b(?:BUY|SELL|LONG|SHORT)\b")

_CLOSE_ACTIONS = {FollowUpAction.CLOSE_ALL, FollowUpAction.CLOSE_PARTIAL}
_MODIFY_ACTIONS = {
    FollowUpAction.MOVE_SL,
    FollowUpAction.MOVE_SL_BE,
    FollowUpAction.MOVE_TP,
    FollowUpAction.CANCEL_PENDING,
}


def _as_utc(value: Any) -> datetime | None:
    """Ramene une date a UTC. Retourne None si la valeur n'est pas une date."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _sort_key(raw: dict[str, Any]) -> tuple[bool, datetime]:
    date = _as_utc(raw.get("date"))
    return (date is None, date or _EPOCH)


def _rate(part: int, total: int) -> float:
    """Pourcentage 0-100 arrondi a une decimale. 0.0 si la mesure n'a pas de base."""
    if total <= 0:
        return 0.0
    return round(part * 100 / total, 1)


def _duplicate_key(parsed: ParsedSignal) -> tuple[str, str, float | None] | None:
    if parsed.symbol is None or parsed.direction is None:
        return None
    entry = parsed.reference_entry
    return (parsed.symbol, parsed.direction.value, round(entry, 5) if entry is not None else None)


@dataclass(slots=True)
class _Tally:
    """Compteurs bruts accumules pendant le balayage des messages."""

    scanned: int = 0
    signal_like: int = 0
    structured: int = 0
    parseable: int = 0
    follow_up: int = 0
    close: int = 0
    modify: int = 0
    duplicates: int = 0
    with_entry: int = 0
    with_stop_loss: int = 0
    with_take_profit: int = 0
    take_profit_total: int = 0
    first_date: datetime | None = None
    last_date: datetime | None = None
    symbols: Counter[str] = field(default_factory=Counter)
    directions: Counter[str] = field(default_factory=Counter)
    tradable: list[dict[str, Any]] = field(default_factory=list)
    recent: list[tuple[datetime, tuple[str, str, float | None]]] = field(default_factory=list)

    @property
    def span_days(self) -> float:
        """Etendue reelle des dates observees, en jours (minimum 1)."""
        if self.first_date is None or self.last_date is None:
            return 1.0
        return max((self.last_date - self.first_date).total_seconds() / 86400.0, 1.0)


def _register_duplicate(tally: _Tally, parsed: ParsedSignal, date: datetime | None) -> None:
    """Compte un doublon : meme symbole, meme direction, meme entree a moins de 30 min."""
    key = _duplicate_key(parsed)
    if key is None or date is None:
        return
    tally.recent = [item for item in tally.recent if date - item[0] <= DUPLICATE_WINDOW]
    if any(previous_key == key for _, previous_key in tally.recent):
        tally.duplicates += 1
    tally.recent.append((date, key))


def _record_signal(
    tally: _Tally, parsed: ParsedSignal, valid: bool, date: datetime | None, message_id: int | None
) -> None:
    """Met a jour les compteurs pour un message reconnu comme signal."""
    tally.structured += 1
    if valid:
        tally.parseable += 1
    if parsed.has_entry:
        tally.with_entry += 1
    if parsed.stop_loss is not None:
        tally.with_stop_loss += 1
    if parsed.take_profits:
        tally.with_take_profit += 1
    tally.take_profit_total += len(parsed.take_profits)
    if parsed.symbol:
        tally.symbols[parsed.symbol] += 1
    if parsed.direction is not None:
        tally.directions[parsed.direction.value] += 1

    _register_duplicate(tally, parsed, date)

    # Seuls les signaux complets (date, instrument, direction, entree, SL, TP)
    # peuvent etre rejoues sur les cours historiques.
    entry = parsed.reference_entry
    complete = (
        date is not None
        and parsed.symbol is not None
        and parsed.direction is not None
        and entry is not None
        and parsed.stop_loss is not None
        and bool(parsed.take_profits)
    )
    if complete:
        tally.tradable.append(
            {
                "messageId": message_id,
                "date": date,
                "symbol": parsed.symbol,
                "direction": parsed.direction,
                "entry": entry,
                "stopLoss": parsed.stop_loss,
                "takeProfits": list(parsed.take_profits),
                "orderType": parsed.order_type,
            }
        )


async def _scan_messages(
    session: AsyncSession,
    channel_id: int | None,
    messages: list[dict[str, Any]],
    aliases: dict[str, str],
) -> _Tally:
    """Rejoue le parser local sur chaque message et accumule les compteurs."""
    tally = _Tally()
    for raw in sorted(messages, key=_sort_key):
        tally.scanned += 1
        date = _as_utc(raw.get("date"))
        if date is not None:
            if tally.first_date is None or date < tally.first_date:
                tally.first_date = date
            if tally.last_date is None or date > tally.last_date:
                tally.last_date = date

        text = str(raw.get("text") or "")
        if not text.strip():
            continue

        # allow_ai=False : aucune requete OpenRouter pendant une analyse de masse.
        parsed, validation = await pipeline.analyze_text(session, text, channel_id, allow_ai=False)
        if parsed.is_signal:
            tally.signal_like += 1
            raw_id = raw.get("messageId")
            _record_signal(tally, parsed, validation.ok, date, raw_id if isinstance(raw_id, int) else None)
            continue

        follow_up = follow_up_parser.parse_follow_up(text, aliases)
        if follow_up is not None:
            tally.follow_up += 1
            if follow_up.action in _CLOSE_ACTIONS:
                tally.close += 1
            elif follow_up.action in _MODIFY_ACTIONS:
                tally.modify += 1
            continue

        if _TRADE_INTENT.search(normalize_upper(text)):
            tally.signal_like += 1
    return tally


def _build_notes(analysis: ChannelAnalysis, tally: _Tally) -> str:
    """Note technique strictement descriptive, en francais neutre."""
    if analysis.first_message_at and analysis.last_message_at:
        period = (
            f"du {analysis.first_message_at.date().isoformat()} "
            f"au {analysis.last_message_at.date().isoformat()}"
        )
    else:
        period = "periode inconnue"

    lines = [
        f"{analysis.messages_scanned} messages analyses ({period}).",
        f"{analysis.signal_like_messages} messages avec intention de trade, "
        f"{tally.structured} signaux structures, {analysis.parsed_messages} signaux interpretables.",
        f"Qualite de structure : {analysis.structure_quality} %. "
        f"Signaux correctement interpretables : {analysis.parseable_rate} %.",
        f"Signaux avec stop loss : {analysis.with_stop_loss_rate} %. "
        f"Signaux avec take profit : {analysis.with_take_profit_rate} % "
        f"({analysis.average_take_profits} take profits en moyenne).",
        f"Frequence observee : {analysis.signals_per_day} signaux par jour.",
        f"Messages de suivi : {analysis.follow_up_messages} "
        f"(dont {analysis.close_messages} fermetures et {analysis.modify_messages} modifications). "
        f"Doublons detectes : {analysis.duplicate_signals}.",
    ]
    if analysis.symbols:
        top = ", ".join(f"{name} ({count})" for name, count in tally.symbols.most_common(5))
        lines.append(f"Instruments observes : {top}.")
    if analysis.directions:
        detail = ", ".join(f"{name} ({count})" for name, count in sorted(analysis.directions.items()))
        lines.append(f"Repartition des directions : {detail}.")
    lines.append("Mesures relevees sur l'historique disponible, sans projection de performance.")
    return "\n".join(lines)


async def analyze_channel(
    session: AsyncSession,
    channel: Channel,
    messages: list[dict[str, Any]],
    run_backtest: bool = False,
    market: MetaTraderService | None = None,
) -> ChannelAnalysis:
    """Analyse l'historique d'un canal et persiste un ``ChannelAnalysis``.

    ``messages`` est une liste de dictionnaires deja recuperes par la couche
    Telegram : ``{"messageId": int, "text": str, "date": datetime,
    "replyToMessageId": int | None}``.

    Si ``run_backtest`` est vrai et qu'un service MT5 est fourni, une simulation
    historique prudente est ajoutee dans le champ ``backtest`` (CDC section 14).
    """
    channel_id = channel.id
    aliases = await channel_repo.channel_aliases(session, channel_id)
    tally = await _scan_messages(session, channel_id, messages, aliases)

    analysis = ChannelAnalysis(
        channel_id=channel_id,
        messages_scanned=tally.scanned,
        signal_like_messages=tally.signal_like,
        parsed_messages=tally.parseable,
        follow_up_messages=tally.follow_up,
        close_messages=tally.close,
        modify_messages=tally.modify,
        duplicate_signals=tally.duplicates,
        structure_quality=_rate(tally.structured, tally.signal_like),
        with_stop_loss_rate=_rate(tally.with_stop_loss, tally.structured),
        with_take_profit_rate=_rate(tally.with_take_profit, tally.structured),
        parseable_rate=_rate(tally.parseable, tally.signal_like),
        average_take_profits=(
            round(tally.take_profit_total / tally.structured, 1) if tally.structured else 0.0
        ),
        signals_per_day=round(tally.parseable / tally.span_days, 1),
        first_message_at=tally.first_date,
        last_message_at=tally.last_date,
        symbols=dict(tally.symbols),
        directions=dict(tally.directions),
    )
    analysis.notes = _build_notes(analysis, tally)
    await channel_repo.save_analysis(session, analysis)

    if run_backtest and market is not None and analysis.id is not None and tally.tradable:
        analysis.backtest = await backtester.backtest_signals(
            session,
            analysis_id=analysis.id,
            channel_id=channel_id or 0,
            signals=tally.tradable,
            market=market,
        )
        await channel_repo.save_analysis(session, analysis)

    logger.info(
        "Analyse du canal %s : %s messages, %s signaux interpretables",
        channel_id,
        tally.scanned,
        tally.parseable,
    )
    await journal.record(
        session,
        event="channel_analyzed",
        message=(
            f"Canal {channel.title or channel_id} analyse : {tally.scanned} messages, "
            f"{tally.parseable} signaux interpretables ({analysis.parseable_rate} %)"
        ),
        category="channel",
        channel_id=channel_id,
    )
    event_bus.publish(
        EventType.CHANNEL_ANALYSIS,
        {
            "channelId": channel_id,
            "analysisId": analysis.id,
            "messagesScanned": analysis.messages_scanned,
            "parseableRate": analysis.parseable_rate,
            "signalsPerDay": analysis.signals_per_day,
        },
    )
    return analysis
