"""Rapports quotidien et hebdomadaire (CDC2 sections 88 et 89).

Le contenu est construit ici ; la planification reste une simple fonction
appelable (``send_daily_report`` / ``send_weekly_report``), ce qui permet de la
declencher depuis une tache de fond, une route d'administration ou un test.

Aucun chiffre n'est invente : tout provient des tables ``trades``,
``decision_records``, ``ai_consensus_records``, ``economic_events`` et
``news_events``. Une periode sans trade le dit franchement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.enums import PositionState
from app.models.intelligence import (
    AIConsensusRecord,
    DecisionRecord,
    DecisionSource,
    EconomicEvent,
    NewsEvent,
    NewsImpact,
    NotificationCategory,
    NotificationEvent,
    NotificationPriority,
)
from app.models.trading import TradeRecord
from app.services.notifications.formatting import NotificationDraft, format_number

SOURCE_TELEGRAM = "Telegram"
SOURCE_DETERMINISTE = "Déterministe"
SOURCE_OPENROUTER = "OpenRouter"
SOURCE_ENSEMBLE = "Ensemble"
SOURCE_MANUAL = "Manuel"
SOURCE_OTHER = "Autre"

SOURCE_ORDER = [
    SOURCE_DETERMINISTE,
    SOURCE_OPENROUTER,
    SOURCE_ENSEMBLE,
    SOURCE_TELEGRAM,
    SOURCE_MANUAL,
    SOURCE_OTHER,
]


@dataclass(slots=True)
class ReportStats:
    """Chiffres bruts d'une periode, sans mise en forme."""

    start: datetime
    end: datetime
    trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    result: float = 0.0
    gains: float = 0.0
    losses_amount: float = 0.0
    average_r: float | None = None
    max_drawdown: float = 0.0
    best_symbol: tuple[str, float] | None = None
    worst_symbol: tuple[str, float] | None = None
    by_source: dict[str, int] = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        decided = self.wins + self.losses
        return (self.wins / decided * 100.0) if decided else 0.0

    @property
    def profit_factor(self) -> float | None:
        if self.losses_amount <= 0:
            return None if self.gains <= 0 else float("inf")
        return self.gains / self.losses_amount


async def closed_trades(
    session: AsyncSession, start: datetime, end: datetime
) -> list[TradeRecord]:
    statement = (
        select(TradeRecord)
        .where(TradeRecord.state == PositionState.CLOSED)
        .where(TradeRecord.closed_at != None)  # noqa: E711
        .where(TradeRecord.closed_at >= start)
        .where(TradeRecord.closed_at < end)
        .order_by(TradeRecord.closed_at)
    )
    result = await session.exec(statement)
    return list(result.all())


async def _trade_source(session: AsyncSession, trade: TradeRecord) -> str:
    """Determine d'ou vient le trade : Telegram, IA locale, OpenRouter, Ensemble."""
    if trade.channel_id is not None:
        return SOURCE_TELEGRAM
    result = await session.exec(
        select(DecisionRecord).where(DecisionRecord.trade_id == trade.id)
    )
    decision = result.first()
    if decision is None:
        return SOURCE_TELEGRAM if trade.signal_id is not None else SOURCE_OTHER
    if decision.source == DecisionSource.TELEGRAM:
        return SOURCE_TELEGRAM
    if decision.source == DecisionSource.MANUAL:
        return SOURCE_MANUAL
    consensus_result = await session.exec(
        select(AIConsensusRecord).where(AIConsensusRecord.decision_id == decision.id)
    )
    consensus = consensus_result.first()
    if consensus is None:
        # Aucune IA n'a ete consultee : la decision vient des regles.
        return SOURCE_DETERMINISTE
    if consensus.primary_model and consensus.secondary_model:
        return SOURCE_ENSEMBLE
    if consensus.primary_model:
        return SOURCE_OPENROUTER
    return SOURCE_DETERMINISTE


async def collect_stats(session: AsyncSession, start: datetime, end: datetime) -> ReportStats:
    """Agrege les positions fermees sur la periode [start, end[."""
    stats = ReportStats(start=start, end=end)
    trades = await closed_trades(session, start, end)
    stats.trades = len(trades)
    if not trades:
        return stats

    per_symbol: dict[str, float] = {}
    r_values: list[float] = []
    cumulative = 0.0
    peak = 0.0

    for trade in trades:
        pnl = float(trade.realized_pnl or 0.0)
        stats.result += pnl
        if pnl > 0:
            stats.wins += 1
            stats.gains += pnl
        elif pnl < 0:
            stats.losses += 1
            stats.losses_amount += abs(pnl)
        else:
            stats.breakeven += 1
        per_symbol[trade.symbol] = per_symbol.get(trade.symbol, 0.0) + pnl
        if trade.r_multiple is not None:
            r_values.append(float(trade.r_multiple))
        cumulative += pnl
        peak = max(peak, cumulative)
        stats.max_drawdown = max(stats.max_drawdown, peak - cumulative)
        source = await _trade_source(session, trade)
        stats.by_source[source] = stats.by_source.get(source, 0) + 1

    if r_values:
        stats.average_r = sum(r_values) / len(r_values)
    ranked = sorted(per_symbol.items(), key=lambda item: item[1], reverse=True)
    stats.best_symbol = ranked[0]
    stats.worst_symbol = ranked[-1]
    return stats


async def upcoming_events(
    session: AsyncSession, start: datetime, end: datetime, limit: int = 5
) -> list[str]:
    """Evenements economiques a fort impact prevus sur la fenetre demandee."""
    statement = (
        select(EconomicEvent)
        .where(EconomicEvent.scheduled_at >= start)
        .where(EconomicEvent.scheduled_at < end)
        .where(EconomicEvent.impact.in_([NewsImpact.HIGH, NewsImpact.CRITICAL]))
        .order_by(EconomicEvent.scheduled_at)
        .limit(limit)
    )
    result = await session.exec(statement)
    lines = []
    for event in result.all():
        moment = event.scheduled_at.strftime("%H:%M")
        currency = f" {event.currency}" if event.currency else ""
        lines.append(f"{moment}{currency} · {event.title}")
    return lines


async def important_news(
    session: AsyncSession, start: datetime, end: datetime, limit: int = 3
) -> list[str]:
    """Actualites a fort impact deja publiees sur la periode."""
    statement = (
        select(NewsEvent)
        .where(NewsEvent.received_at >= start)
        .where(NewsEvent.received_at < end)
        .where(NewsEvent.impact.in_([NewsImpact.HIGH, NewsImpact.CRITICAL]))
        .order_by(NewsEvent.received_at.desc())
        .limit(limit)
    )
    result = await session.exec(statement)
    return [news.title[:120] for news in result.all()]


def _source_lines(stats: ReportStats) -> list[str]:
    if not stats.by_source:
        return ["Aucune position fermée."]
    lines = []
    for source in SOURCE_ORDER:
        count = stats.by_source.get(source)
        if count:
            lines.append(f"{source} : {count}")
    for source, count in stats.by_source.items():
        if source not in SOURCE_ORDER:
            lines.append(f"{source} : {count}")
    return lines


def _result_line(stats: ReportStats) -> str:
    sign = "+" if stats.result >= 0 else ""
    return f"Résultat : {sign}{format_number(stats.result, 2)}"


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


async def build_daily_report(
    session: AsyncSession, day: date | None = None
) -> NotificationDraft:
    """CDC2 88 : journal du jour, avec les news importantes du lendemain."""
    target = day or datetime.now(UTC).date()
    start, end = day_bounds(target)
    stats = await collect_stats(session, start, end)
    tomorrow_start, tomorrow_end = day_bounds(target + timedelta(days=1))
    tomorrow = await upcoming_events(session, tomorrow_start, tomorrow_end)

    blocks = [
        f"Trades : {stats.trades}",
        f"Gagnants : {stats.wins}",
        f"Perdants : {stats.losses}",
        _result_line(stats),
    ]
    if stats.trades:
        blocks.append(f"Taux de réussite : {stats.win_rate:.0f} %")
    blocks.append("")
    blocks.append("Par source")
    blocks.extend(_source_lines(stats))
    blocks.append("")
    blocks.append("Actualités importantes demain")
    blocks.extend(tomorrow or ["Aucun événement à fort impact annoncé."])

    return NotificationDraft(
        category=NotificationCategory.DAILY_REPORT,
        priority=NotificationPriority.MEDIUM,
        title=f"📊 TRADEPILOT — JOURNAL DU {target.strftime('%d/%m')}",
        body="\n".join(blocks),
        data={"route": "reports", "period": "daily", "day": target.isoformat()},
    )


async def build_weekly_report(
    session: AsyncSession, end_day: date | None = None
) -> NotificationDraft:
    """CDC2 89 : bilan des sept derniers jours."""
    target = end_day or datetime.now(UTC).date()
    end = datetime(target.year, target.month, target.day, tzinfo=UTC) + timedelta(days=1)
    start = end - timedelta(days=7)
    stats = await collect_stats(session, start, end)

    profit_factor = stats.profit_factor
    if profit_factor is None:
        factor_text = "—"
    elif profit_factor == float("inf"):
        factor_text = "∞ (aucune perte)"
    else:
        factor_text = f"{profit_factor:.2f}"

    blocks = [
        f"Du {start.strftime('%d/%m')} au {target.strftime('%d/%m')}",
        "",
        f"Trades : {stats.trades}",
        f"Taux de réussite : {stats.win_rate:.0f} %",
        f"Facteur de profit : {factor_text}",
        f"R moyen : {format_number(stats.average_r, 2) if stats.average_r is not None else '—'}",
        f"Drawdown max : {format_number(stats.max_drawdown, 2)}",
        _result_line(stats),
    ]
    if stats.best_symbol:
        blocks.append(
            f"Meilleur instrument : {stats.best_symbol[0]} "
            f"({format_number(stats.best_symbol[1], 2)})"
        )
    if stats.worst_symbol:
        blocks.append(
            f"Instrument le plus faible : {stats.worst_symbol[0]} "
            f"({format_number(stats.worst_symbol[1], 2)})"
        )
    blocks.append("")
    blocks.append("Performance par source")
    blocks.extend(_source_lines(stats))

    return NotificationDraft(
        category=NotificationCategory.DAILY_REPORT,
        priority=NotificationPriority.MEDIUM,
        title=f"🗓 TRADEPILOT — BILAN HEBDOMADAIRE {target.strftime('%d/%m')}",
        body="\n".join(blocks),
        data={"route": "reports", "period": "weekly", "day": target.isoformat()},
    )


# ---------------------------------------------------------------------------
# Planification : de simples fonctions appelables
# ---------------------------------------------------------------------------

async def send_daily_report(
    session: AsyncSession | None = None, day: date | None = None
) -> NotificationEvent | None:
    from app.services.notifications.service import _use_session, notification_service

    async with _use_session(session) as db_session:
        draft = await build_daily_report(db_session, day)
        return await notification_service.send(draft, session=db_session)


async def send_weekly_report(
    session: AsyncSession | None = None, end_day: date | None = None
) -> NotificationEvent | None:
    from app.services.notifications.service import _use_session, notification_service

    async with _use_session(session) as db_session:
        draft = await build_weekly_report(db_session, end_day)
        return await notification_service.send(draft, session=db_session)
