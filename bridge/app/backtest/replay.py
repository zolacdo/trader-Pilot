"""Rejoue la decision du watcher pas a pas, puis deroule chaque trade retenu.

Ce qui est reproduit a l'identique : l'analyse multi-unites, les niveaux
(entree, stop, objectifs), la notation, et toutes les protections de
``risk.evaluate`` sauf le seuil de score.

Ce qui ne l'est pas, et pourquoi :

* les actualites (sentiment, fondamental, calendrier) : la base n'en garde
  que quelques semaines. Ces criteres restent « indisponibles », ce qui
  plafonne le score publie a environ 77. On enregistre donc ``raw_score``
  (la note des seuls criteres mesures) et le seuil se juge apres coup, par
  tranches, au lieu d'etre impose pendant le rejeu ;
* l'avis de l'IA, qui ne modifie pas les niveaux ;
* le dimensionnement en lots : tout est mesure en R.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from app.backtest.market import HistoricalMarket
from app.backtest.simulate import Bars, ExitPolicy, simulate_trade
from app.models.enums import Direction
from app.services.technical_analysis import MultiTimeframeAnalyzer, profile_for
from app.watcher import risk
from app.watcher.analysis.context import (
    MarketContext,
    _primary_timeframe,
    _read_quality,
)
from app.watcher.analysis.liquidity import read_liquidity
from app.watcher.analysis.price_action import read_price_action
from app.watcher.analysis.volatility import read_volatility
from app.watcher.analysis.volume import read_volume
from app.watcher.config import WatcherConfig
from app.watcher.engine import WatcherEngine
from app.watcher.models import EntryType

_analyzer = MultiTimeframeAnalyzer()
# ``_best_direction`` n'utilise pas le publicateur.
_engine = WatcherEngine(publisher=None)  # type: ignore[arg-type]

POLICIES = (ExitPolicy.LADDER, ExitPolicy.FIRST_TARGET, ExitPolicy.LAST_TARGET)


@dataclass(slots=True)
class Candidate:
    """Un signal que le watcher aurait emis, et ce qu'il serait devenu."""

    symbol: str
    time: datetime
    direction: str
    entry_type: str
    entry: float
    stop: float
    targets: list[float]
    first_rr: float | None
    raw_score: float
    score: float
    bias: str
    hour: int
    results: dict[str, dict[str, Any]] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "symbol": self.symbol,
            "time": self.time.isoformat(),
            "direction": self.direction,
            "entry_type": self.entry_type,
            "entry": self.entry,
            "stop": self.stop,
            "targets": "/".join(str(t) for t in self.targets),
            "first_rr": self.first_rr,
            "raw_score": self.raw_score,
            "score": self.score,
            "bias": self.bias,
            "hour": self.hour,
        }
        for policy, result in self.results.items():
            for key, value in result.items():
                row[f"{policy.lower()}_{key}"] = value
        return row


@dataclass(slots=True)
class _Book:
    """Signaux en cours, pour l'anti-doublon et la cadence de ``risk.evaluate``."""

    open_until: list[tuple[datetime, str]] = field(default_factory=list)
    last_signal_at: datetime | None = None
    per_day: dict[str, int] = field(default_factory=dict)

    def state(self, now: datetime, direction: Direction) -> risk.PortfolioState:
        self.open_until = [(end, d) for end, d in self.open_until if end > now]
        return risk.PortfolioState(
            active_signals=len(self.open_until),
            signals_today=self.per_day.get(now.date().isoformat(), 0),
            active_same_symbol=len(self.open_until),
            active_same_direction=any(d == direction.value for _, d in self.open_until),
            last_signal_at=self.last_signal_at,
        )

    def add(self, now: datetime, end: datetime, direction: Direction) -> None:
        self.open_until.append((end, direction.value))
        self.last_signal_at = now
        key = now.date().isoformat()
        self.per_day[key] = self.per_day.get(key, 0) + 1


async def build_context(market: HistoricalMarket, config: WatcherConfig) -> MarketContext:
    """``analysis.context.build_context`` sans actualites ni base de donnees."""
    moment = market.moment()
    symbol = market.symbol
    context = MarketContext(symbol=symbol, broker_symbol=symbol, generated_at=moment)
    profile = profile_for(config.profile)
    context.view = await _analyzer.analyse(market, symbol, profile, bars=config.bars)  # type: ignore[arg-type]
    context.primary_timeframe = _primary_timeframe(profile, context.view)
    if context.primary_timeframe is not None:
        context.primary = context.view.analysis_for(context.primary_timeframe)
        context.candles = await market.candles(symbol, context.primary_timeframe, config.bars)
    context.quality = _read_quality(context.candles, config, moment, context.primary_timeframe)
    if context.candles and context.primary is not None:
        context.volatility = read_volatility(context.candles)
        context.volume = read_volume(context.candles, context.primary.breakout)
        context.price_action = read_price_action(context.candles)
        context.liquidity = read_liquidity(
            context.candles, context.primary.swings, context.primary.atr
        )
    context.quote = await market.quote(symbol)
    context.symbol_info = await market.symbol_info(symbol)
    context.market_state = await market.market_state(symbol)
    return context


def execution_bars(market: HistoricalMarket) -> Bars:
    base = market.frames[market.base]
    return Bars(
        time=base["time"],
        open=base["open"],
        high=base["high"],
        low=base["low"],
        close=base["close"],
        spread=base["spread"].astype(float),
        point=market.info.point,
        seconds=market.base_seconds,
    )


async def replay_symbol(
    market: HistoricalMarket,
    config: WatcherConfig,
    start: datetime,
    end: datetime,
    step_minutes: int = 15,
    progress: Any = None,
) -> list[Candidate]:
    """Toutes les decisions qu'aurait prises le watcher entre ``start`` et ``end``."""
    # Le seuil de score est juge apres coup, par tranches (voir l'en-tete).
    unbounded = replace(config, minimum_score=0.0)
    bars = execution_bars(market)
    times = bars.time
    step = step_minutes * 60
    book = _Book()
    candidates: list[Candidate] = []

    first = int(start.timestamp())
    last = int(end.timestamp())
    cursors = [
        int(t) + market.base_seconds
        for t in times
        if first <= int(t) + market.base_seconds <= last and (int(t) + market.base_seconds) % step == 0
    ]
    for count, cursor in enumerate(cursors):
        if progress is not None and count % 500 == 0:
            progress(market.symbol, count, len(cursors))
        market.cursor = cursor
        now = market.moment()
        context = await build_context(market, config)
        if not context.usable:
            continue
        direction, card, levels = _engine._best_direction(context, unbounded)
        if levels is None or card is None:
            continue
        verdict = risk.evaluate(
            context, direction, levels, card, unbounded, book.state(now, direction), now
        )
        if not verdict.approved:
            continue

        buy = direction is Direction.BUY
        candidate = Candidate(
            symbol=market.symbol,
            time=now,
            direction=direction.value,
            entry_type=levels.entry_type.value,
            entry=levels.entry,
            stop=levels.stop_loss,
            targets=list(levels.targets),
            first_rr=levels.first_risk_reward,
            raw_score=round(card.raw_score, 1),
            score=round(card.score, 1),
            bias=context.bias.value,
            hour=now.hour,
        )
        start_index = market.last_base_index() + 1
        pending = levels.entry_type is EntryType.STOP
        busy_until = now + timedelta(minutes=config.signal_ttl_minutes)
        for policy in POLICIES:
            result = simulate_trade(
                bars,
                start_index,
                buy,
                levels.entry,
                levels.stop_loss,
                list(levels.targets),
                pending=pending,
                policy=policy,
                pending_minutes=config.signal_ttl_minutes,
            )
            candidate.results[policy.value] = {
                "filled": result.filled,
                "exit": result.exit_reason,
                "r": round(result.r, 3),
                "mfe": round(result.max_favorable_r, 3),
                "tp": result.targets_hit,
                "closed_at": (
                    datetime.fromtimestamp(result.exit_time, UTC).isoformat()
                    if result.exit_time
                    else None
                ),
            }
            if policy is ExitPolicy.LADDER and result.exit_time:
                busy_until = max(busy_until, datetime.fromtimestamp(result.exit_time, UTC))
        book.add(now, busy_until, direction)
        candidates.append(candidate)
    return candidates


__all__ = ["Candidate", "build_context", "replay_symbol"]
