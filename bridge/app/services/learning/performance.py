"""Lecture des performances apprises, par strategie et par origine (CDC2 49).

Ces fonctions ne font que lire et regrouper : elles ne modifient jamais un
parametre. Une mesure impossible a calculer vaut None, jamais zero.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import DecisionSource, StrategyPerformance
from app.repositories import pattern_repo
from app.services.learning.recorder import LEARNING_NOTE, collect_records


def _rate(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(part * 100 / total, 2)


def _empty() -> dict[str, Any]:
    return {"trades": 0, "wins": 0, "losses": 0, "net_r": 0.0, "net_pnl": 0.0, "max_drawdown": 0.0}


def _accumulate(bucket: dict[str, Any], row: StrategyPerformance) -> None:
    bucket["trades"] += row.trades
    bucket["wins"] += row.wins
    bucket["losses"] += row.losses
    bucket["net_r"] += row.net_r
    bucket["net_pnl"] += row.net_pnl
    bucket["max_drawdown"] = max(bucket["max_drawdown"], row.max_drawdown)


def _present(key: str, bucket: dict[str, Any], label: str) -> dict[str, Any]:
    trades = bucket["trades"]
    return {
        label: key,
        "trades": trades,
        "wins": bucket["wins"],
        "losses": bucket["losses"],
        "winRate": _rate(bucket["wins"], trades),
        "netR": round(bucket["net_r"], 3),
        "netPnl": round(bucket["net_pnl"], 2),
        "averageR": round(bucket["net_r"] / trades, 3) if trades else None,
        "maxDrawdown": round(bucket["max_drawdown"], 2),
    }


def _since_day(days: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).date().isoformat()


async def by_strategy(session: AsyncSession, days: int = 90) -> list[dict[str, Any]]:
    rows = await pattern_repo.list_strategy_performance(session, since_day=_since_day(days))
    buckets: dict[str, dict[str, Any]] = defaultdict(_empty)
    for row in rows:
        _accumulate(buckets[row.strategy], row)
    result = [_present(name, bucket, "strategy") for name, bucket in buckets.items()]
    result.sort(key=lambda item: item["trades"], reverse=True)
    return result


async def by_source(session: AsyncSession, days: int = 90) -> list[dict[str, Any]]:
    rows = await pattern_repo.list_strategy_performance(session, since_day=_since_day(days))
    buckets: dict[str, dict[str, Any]] = defaultdict(_empty)
    for row in rows:
        key = row.source.value if isinstance(row.source, DecisionSource) else str(row.source)
        _accumulate(buckets[key], row)
    result = [_present(name, bucket, "source") for name, bucket in buckets.items()]
    result.sort(key=lambda item: item["trades"], reverse=True)
    return result


async def by_day(session: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    rows = await pattern_repo.list_strategy_performance(session, since_day=_since_day(days))
    buckets: dict[str, dict[str, Any]] = defaultdict(_empty)
    for row in rows:
        _accumulate(buckets[row.day], row)
    result = [_present(name, bucket, "day") for name, bucket in buckets.items()]
    result.sort(key=lambda item: item["day"], reverse=True)
    return result


async def by_regime(session: AsyncSession, days: int = 90, limit: int = 2000) -> list[dict[str, Any]]:
    """Performance par regime de marche, lue depuis les enregistrements detailles."""
    rows = await collect_records(session, limit=limit)
    floor = _since_day(days)
    buckets: dict[str, dict[str, Any]] = defaultdict(_empty)
    for row in rows:
        if (row.get("day") or "") < floor:
            continue
        key = row.get("regime") or "INCONNU"
        bucket = buckets[key]
        bucket["trades"] += 1
        if row.get("result") == "WIN":
            bucket["wins"] += 1
        elif row.get("result") == "LOSS":
            bucket["losses"] += 1
        if row.get("rMultiple") is not None:
            bucket["net_r"] += row["rMultiple"]
        if row.get("realizedPnl") is not None:
            bucket["net_pnl"] += row["realizedPnl"]
    result = [_present(name, bucket, "regime") for name, bucket in buckets.items()]
    result.sort(key=lambda item: item["trades"], reverse=True)
    return result


async def overview(session: AsyncSession, days: int = 90) -> dict[str, Any]:
    """Synthese complete destinee a l'API et a l'application mobile."""
    strategies = await by_strategy(session, days)
    sources = await by_source(session, days)
    return {
        "days": days,
        "bySource": sources,
        "byStrategy": strategies,
        "byRegime": await by_regime(session, days),
        "byDay": await by_day(session, min(days, 30)),
        "totalTrades": sum(item["trades"] for item in strategies),
        "note": LEARNING_NOTE,
    }


__all__ = ["by_day", "by_regime", "by_source", "by_strategy", "overview"]
