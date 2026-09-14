"""Statistiques reelles calculees depuis les trades fermes (CDC sections 36 et 72).

Toutes les mesures proviennent de la table ``trades`` : rien n'est estime ni
extrapole. Lorsqu'une mesure n'a pas de sens (aucun trade, aucune perte pour
un profit factor, aucun R renseigne), la valeur retournee est ``None`` et non
zero : un zero laisserait croire a un resultat mesure.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.enums import ExecutionMode, PositionState
from app.models.telegram import Channel
from app.models.trading import TradeRecord
from app.repositories import channel_repo

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _closing_time(trade: TradeRecord) -> datetime:
    """Date de cloture, avec repli sur l'ouverture pour garder un ordre stable."""
    return _as_utc(trade.closed_at) or _as_utc(trade.opened_at) or _EPOCH


def _ratio(part: float, total: float) -> float | None:
    """Pourcentage arrondi, ou None si le denominateur est nul."""
    if total <= 0:
        return None
    return round(part * 100 / total, 2)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _max_drawdown(trades: list[TradeRecord]) -> float | None:
    """Plus forte baisse de la courbe d'equity cumulee, en valeur positive."""
    if not trades:
        return None
    peak = 0.0
    equity = 0.0
    worst = 0.0
    for trade in sorted(trades, key=_closing_time):
        equity += trade.realized_pnl
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(abs(worst), 2)


def _streaks(trades: list[TradeRecord]) -> tuple[int, int]:
    """Plus longue serie de pertes puis plus longue serie de gains."""
    worst_losses = 0
    worst_wins = 0
    losses = 0
    wins = 0
    for trade in sorted(trades, key=_closing_time):
        if trade.realized_pnl > 0:
            wins += 1
            losses = 0
        elif trade.realized_pnl < 0:
            losses += 1
            wins = 0
        else:
            wins = 0
            losses = 0
        worst_wins = max(worst_wins, wins)
        worst_losses = max(worst_losses, losses)
    return worst_losses, worst_wins


async def _load_closed(
    session: AsyncSession,
    execution_mode: ExecutionMode | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    channel_id: int | None = None,
) -> list[TradeRecord]:
    """Charge les trades fermes correspondant aux filtres demandes."""
    statement = select(TradeRecord).where(TradeRecord.state == PositionState.CLOSED)
    if execution_mode is not None:
        statement = statement.where(TradeRecord.execution_mode == execution_mode)
    if since is not None:
        statement = statement.where(TradeRecord.closed_at >= since)
    if until is not None:
        statement = statement.where(TradeRecord.closed_at < until)
    if channel_id is not None:
        statement = statement.where(TradeRecord.channel_id == channel_id)
    result = await session.exec(statement.order_by(TradeRecord.closed_at))
    return list(result.all())


def _summarize(trades: list[TradeRecord]) -> dict[str, Any]:
    """Bloc de mesures commun a toutes les vues (global, par symbole, par jour)."""
    wins = [trade for trade in trades if trade.realized_pnl > 0]
    losses = [trade for trade in trades if trade.realized_pnl < 0]
    break_even = [trade for trade in trades if trade.realized_pnl == 0]
    gross_profit = sum(trade.realized_pnl for trade in wins)
    gross_loss = abs(sum(trade.realized_pnl for trade in losses))
    r_values = [trade.r_multiple for trade in trades if trade.r_multiple is not None]
    total = len(trades)
    pnl = sum(trade.realized_pnl for trade in trades)

    consecutive_losses, consecutive_wins = _streaks(trades)
    return {
        "pnl": round(pnl, 2),
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "breakEven": len(break_even),
        "winRate": _ratio(len(wins), total),
        "lossRate": _ratio(len(losses), total),
        "grossProfit": round(gross_profit, 2),
        "grossLoss": round(gross_loss, 2),
        # Sans aucune perte, le profit factor est mathematiquement infini :
        # on ne retourne pas un chiffre trompeur.
        "profitFactor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "averageWin": round(gross_profit / len(wins), 2) if wins else None,
        "averageLoss": round(sum(t.realized_pnl for t in losses) / len(losses), 2) if losses else None,
        "averageR": _mean([float(value) for value in r_values]),
        "bestTrade": round(max(trade.realized_pnl for trade in trades), 2) if trades else None,
        "worstTrade": round(min(trade.realized_pnl for trade in trades), 2) if trades else None,
        "maxDrawdown": _max_drawdown(trades),
        "consecutiveLosses": consecutive_losses,
        "consecutiveWins": consecutive_wins,
        "expectancy": round(pnl / total, 2) if total else None,
    }


async def global_statistics(
    session: AsyncSession,
    execution_mode: ExecutionMode | None = None,
    since: datetime | None = None,
    channel_id: int | None = None,
) -> dict[str, Any]:
    """Statistiques globales calculees sur les trades fermes (CDC section 36)."""
    trades = await _load_closed(session, execution_mode, since, None, channel_id)
    summary = _summarize(trades)
    summary["executionMode"] = execution_mode.value if execution_mode else None
    summary["since"] = since.isoformat() if since else None
    summary["channelId"] = channel_id
    return summary


def _group(
    trades: list[TradeRecord],
    key_name: str,
    key_of: Callable[[TradeRecord], Any],
) -> list[dict[str, Any]]:
    """Regroupe les trades puis calcule le meme bloc de mesures par groupe."""
    buckets: dict[Any, list[TradeRecord]] = defaultdict(list)
    for trade in trades:
        buckets[key_of(trade)].append(trade)
    rows: list[dict[str, Any]] = []
    for key, group in buckets.items():
        row: dict[str, Any] = {key_name: key}
        row.update(_summarize(group))
        rows.append(row)
    return rows


async def by_symbol(
    session: AsyncSession,
    execution_mode: ExecutionMode | None = None,
    since: datetime | None = None,
    channel_id: int | None = None,
) -> list[dict[str, Any]]:
    """Resultats par instrument, du P&L le plus eleve au plus faible."""
    trades = await _load_closed(session, execution_mode, since, None, channel_id)
    rows = _group(trades, "symbol", lambda trade: trade.symbol)
    rows.sort(key=lambda row: row["pnl"], reverse=True)
    return rows


async def by_day(
    session: AsyncSession,
    execution_mode: ExecutionMode | None = None,
    since: datetime | None = None,
    channel_id: int | None = None,
) -> list[dict[str, Any]]:
    """Resultats par journee UTC de cloture, du plus ancien au plus recent."""
    trades = await _load_closed(session, execution_mode, since, None, channel_id)
    rows = _group(trades, "day", lambda trade: _closing_time(trade).date().isoformat())
    rows.sort(key=lambda row: row["day"])
    return rows


async def by_hour(
    session: AsyncSession,
    execution_mode: ExecutionMode | None = None,
    since: datetime | None = None,
    channel_id: int | None = None,
) -> list[dict[str, Any]]:
    """Resultats par heure UTC d'ouverture de la position, de 0 a 23."""
    trades = await _load_closed(session, execution_mode, since, None, channel_id)
    rows = _group(trades, "hour", lambda trade: (_as_utc(trade.opened_at) or _EPOCH).hour)
    rows.sort(key=lambda row: row["hour"])
    return rows


async def by_channel(
    session: AsyncSession,
    execution_mode: ExecutionMode | None = None,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Resultats par canal d'origine, du P&L le plus eleve au plus faible."""
    trades = await _load_closed(session, execution_mode, since)
    rows = _group(trades, "channelId", lambda trade: trade.channel_id)
    rows.sort(key=lambda row: row["pnl"], reverse=True)
    return rows


def _paper_block(trades: Iterable[TradeRecord]) -> dict[str, Any]:
    """Mesures paper reduites utilisees par le tableau de comparaison."""
    items = list(trades)
    summary = _summarize(items)
    return {
        "paperTrades": summary["trades"],
        "paperPnl": summary["pnl"],
        "paperWinRate": summary["winRate"],
        "paperDrawdown": summary["maxDrawdown"],
        "averageR": summary["averageR"],
    }


async def compare_channels(session: AsyncSession) -> list[dict[str, Any]]:
    """Tableau de comparaison des canaux (CDC section 72).

    Les colonnes sont des donnees observees : mesures de la derniere analyse et
    resultats reels du paper trading. Aucun canal n'est designe comme
    "meilleur" : le classement appartient a l'utilisateur.
    """
    channels: list[Channel] = await channel_repo.list_channels(session)
    paper_trades = await _load_closed(session, ExecutionMode.PAPER)
    by_channel_id: dict[int | None, list[TradeRecord]] = defaultdict(list)
    for trade in paper_trades:
        by_channel_id[trade.channel_id].append(trade)

    rows: list[dict[str, Any]] = []
    for channel in channels:
        analysis = await channel_repo.latest_analysis(session, channel.id) if channel.id else None
        row: dict[str, Any] = {
            "channelId": channel.id,
            "title": channel.title,
            "username": channel.username,
            "monitored": channel.monitored,
            "signalsDetected": analysis.parsed_messages if analysis else channel.signals_count,
            "messagesScanned": analysis.messages_scanned if analysis else None,
            "parseRate": analysis.parseable_rate if analysis else None,
            "slRate": analysis.with_stop_loss_rate if analysis else None,
            "tpRate": analysis.with_take_profit_rate if analysis else None,
            "signalsPerDay": analysis.signals_per_day if analysis else None,
            "analysedAt": analysis.created_at.isoformat() if analysis else None,
            "historyAvailable": bool(analysis is not None and analysis.backtest),
            "backtest": analysis.backtest if analysis else None,
        }
        row.update(_paper_block(by_channel_id.get(channel.id, [])))
        rows.append(row)
    return rows


async def daily_summary(session: AsyncSession, day: str | None = None) -> dict[str, Any]:
    """Resume de la journee UTC pour la page d'accueil (CDC section 31).

    ``day`` est une date ``AAAA-MM-JJ``. Sans argument, la journee UTC courante
    est utilisee.
    """
    try:
        target = date.fromisoformat(day) if day else datetime.now(UTC).date()
    except ValueError:
        target = datetime.now(UTC).date()
    start = datetime.combine(target, time.min, tzinfo=UTC)
    trades = await _load_closed(session, since=start, until=start + timedelta(days=1))

    profit = sum(trade.realized_pnl for trade in trades if trade.realized_pnl > 0)
    loss = abs(sum(trade.realized_pnl for trade in trades if trade.realized_pnl < 0))
    summary = _summarize(trades)
    return {
        "day": target.isoformat(),
        "profit": round(profit, 2),
        "loss": round(loss, 2),
        "netPnl": summary["pnl"],
        "trades": summary["trades"],
        "wins": summary["wins"],
        "losses": summary["losses"],
        "winRate": summary["winRate"],
        "drawdown": summary["maxDrawdown"],
    }
