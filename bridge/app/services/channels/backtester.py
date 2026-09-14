"""Simulation historique prudente des signaux passes d'un canal (CDC section 14).

Chaque signal complet (date, instrument, direction, entree, SL, au moins un TP)
est rejoue bougie par bougie sur les cours M15 fournis par MT5. La simulation
est volontairement pessimiste : aucune issue n'est devinee, aucun resultat
n'est invente. En cas de doute, l'issue est ``UNDETERMINED`` ou ``AMBIGUOUS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.enums import BacktestOutcome, Direction, OrderType
from app.models.trading import BacktestResult
from app.services.mt5.interface import Candle, MetaTraderService

logger = get_logger(__name__)

# M15 : compromis entre precision de la simulation et volume de bougies a
# recuperer. Une bougie plus fine reduirait le nombre de cas ambigus mais
# depasse ce que le terminal renvoie confortablement sur plusieurs mois.
TIMEFRAME = "M15"

# Au-dela de cette duree, un signal historique est considere comme non
# tranche : on ne suppose pas ce qui s'est passe ensuite.
MAX_WINDOW = timedelta(days=7)

DISCLAIMER = "Simulation historique indicative - elle ne garantit aucune performance future."

# Hypothese prudente retenue pour une bougie ambigue : le trade est compte au
# pire (-1 R). Il n'est JAMAIS compte comme gagnant.
AMBIGUOUS_R = -1.0

_MARKET_ORDER_TYPES = {None, OrderType.MARKET}


class SymbolResolverLike(Protocol):
    """Contrat minimal attendu d'un resolveur de symboles broker."""

    async def resolve(self, session: AsyncSession, canonical: str, persist: bool = True) -> Any | None: ...


@dataclass(slots=True)
class _HistoricSignal:
    """Signal historique normalise, pret a etre rejoue."""

    message_id: int | None
    date: datetime
    symbol: str
    direction: Direction
    entry: float
    stop_loss: float
    take_profit: float
    market_entry: bool

    @property
    def risk(self) -> float:
        """Distance entre l'entree et le stop loss, toujours positive."""
        if self.direction is Direction.BUY:
            return self.entry - self.stop_loss
        return self.stop_loss - self.entry


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if raw.get(key) is not None:
            return raw[key]
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _as_direction(value: Any) -> Direction | None:
    if isinstance(value, Direction):
        return value
    if isinstance(value, str):
        try:
            return Direction(value.upper())
        except ValueError:
            return None
    return None


def _normalize(raw: dict[str, Any]) -> _HistoricSignal | None:
    """Convertit un dictionnaire de signal historique. None si incomplet."""
    date = _as_utc(_first(raw, "date", "signalDate", "signal_date", "messageDate"))
    symbol = _first(raw, "symbol", "normalizedSymbol", "normalized_symbol")
    direction = _as_direction(_first(raw, "direction"))
    entry = _as_float(_first(raw, "entry", "entryPrice", "entry_price"))
    if entry is None:
        low = _as_float(_first(raw, "entryMin", "entry_min"))
        high = _as_float(_first(raw, "entryMax", "entry_max"))
        entry = (low + high) / 2 if low is not None and high is not None else None
    stop_loss = _as_float(_first(raw, "stopLoss", "stop_loss"))
    targets = _first(raw, "takeProfits", "take_profits", "takeProfit", "take_profit")
    if isinstance(targets, int | float):
        targets = [targets]
    take_profit = None
    if isinstance(targets, list | tuple) and targets:
        take_profit = _as_float(targets[0])

    if date is None or not symbol or direction is None:
        return None
    if entry is None or stop_loss is None or take_profit is None:
        return None

    order_type = _first(raw, "orderType", "order_type")
    signal = _HistoricSignal(
        message_id=_first(raw, "messageId", "message_id"),
        date=date,
        symbol=str(symbol).upper(),
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        market_entry=order_type in _MARKET_ORDER_TYPES,
    )
    return signal if signal.risk > 0 else None


def _replay(signal: _HistoricSignal, candles: list[Candle]) -> tuple[BacktestOutcome, float | None, str]:
    """Rejoue le signal bougie par bougie et retourne (issue, prix de sortie, detail).

    REGLE CRITIQUE ET NON NEGOCIABLE : avec des donnees OHLC, une bougie ne
    donne que l'ouverture, le plus haut, le plus bas et la cloture. Si dans une
    MEME bougie le stop loss et le take profit sont tous deux atteignables
    (pour un achat : ``low <= SL`` et ``high >= TP``), il est strictement
    impossible de savoir lequel des deux prix a ete touche en premier. Deviner
    reviendrait a fabriquer un resultat. L'issue est donc ``AMBIGUOUS`` et le
    trade n'est jamais compte comme gagnant.
    """
    buy = signal.direction is Direction.BUY
    opened = False
    entry_price = signal.entry

    for candle in candles:
        if not opened:
            if signal.market_entry:
                # Entree au marche : la position est prise des la premiere bougie.
                entry_price = candle.open
                opened = True
            elif candle.low <= signal.entry <= candle.high:
                entry_price = signal.entry
                opened = True
            else:
                continue

        stop_reachable = candle.low <= signal.stop_loss if buy else candle.high >= signal.stop_loss
        target_reachable = candle.high >= signal.take_profit if buy else candle.low <= signal.take_profit

        if stop_reachable and target_reachable:
            return (
                BacktestOutcome.AMBIGUOUS,
                None,
                "SL et TP atteignables dans la meme bougie M15 : ordre reel inconnu",
            )
        if stop_reachable:
            return BacktestOutcome.LOSS, signal.stop_loss, "Stop loss atteint"
        if target_reachable:
            return BacktestOutcome.WIN, signal.take_profit, "Take profit 1 atteint"

    if not opened:
        return (
            BacktestOutcome.UNDETERMINED,
            None,
            "Prix d'entree jamais atteint sur la fenetre observee",
        )
    last_close = candles[-1].close
    detail = f"Toujours ouvert apres {len(candles)} bougies (entree a {entry_price})"
    return BacktestOutcome.OPEN, last_close, detail


def _r_multiple(signal: _HistoricSignal, exit_price: float | None) -> float | None:
    """R multiple signe selon la direction. None si le prix de sortie est inconnu."""
    if exit_price is None or signal.risk <= 0:
        return None
    if signal.direction is Direction.BUY:
        return round((exit_price - signal.entry) / signal.risk, 3)
    return round((signal.entry - exit_price) / signal.risk, 3)


async def _resolve_symbol(
    session: AsyncSession, symbol: str, resolver: SymbolResolverLike | None, cache: dict[str, str | None]
) -> str | None:
    """Traduit le symbole canonique en symbole broker. None s'il est introuvable."""
    if symbol in cache:
        return cache[symbol]
    broker_symbol: str | None = symbol
    if resolver is not None:
        try:
            resolved = await resolver.resolve(session, symbol)
        except Exception as exc:  # le terminal peut etre indisponible
            logger.warning("Resolution du symbole %s impossible : %s", symbol, exc)
            resolved = None
        broker_symbol = getattr(resolved, "broker_symbol", None) if resolved is not None else None
    cache[symbol] = broker_symbol
    return broker_symbol


def _drawdown(curve: list[float]) -> float:
    """Plus forte baisse de la courbe cumulee de R, en valeur positive."""
    peak = 0.0
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return round(abs(worst), 3)


async def backtest_signals(
    session: AsyncSession,
    analysis_id: int,
    channel_id: int,
    signals: list[dict[str, Any]],
    market: MetaTraderService,
    symbol_resolver: SymbolResolverLike | None = None,
) -> dict[str, Any]:
    """Rejoue les signaux historiques et persiste un ``BacktestResult`` par signal teste.

    Retourne un resume agrege. Les issues ``AMBIGUOUS`` sont comptees au pire
    (-1 R) et ne sont jamais des gains ; ``UNDETERMINED`` et ``OPEN`` ne
    participent a aucune moyenne.
    """
    tested: list[_HistoricSignal] = []
    for raw in signals:
        normalized = _normalize(raw)
        if normalized is not None:
            tested.append(normalized)
    tested.sort(key=lambda item: item.date)

    counts = dict.fromkeys(BacktestOutcome, 0)
    cache: dict[str, str | None] = {}
    curve: list[float] = []
    cumulative = 0.0
    total_r = 0.0
    decided = 0

    for signal in tested:
        broker_symbol = await _resolve_symbol(session, signal.symbol, symbol_resolver, cache)
        outcome = BacktestOutcome.UNDETERMINED
        detail = "Instrument indisponible chez le broker"
        exit_price: float | None = None

        if broker_symbol:
            end = signal.date + MAX_WINDOW
            try:
                candles = await market.candles(broker_symbol, TIMEFRAME, signal.date, end)
            except Exception as exc:  # historique absent ou terminal ferme
                logger.warning("Cours historiques indisponibles pour %s : %s", broker_symbol, exc)
                candles = []
            if candles:
                outcome, exit_price, detail = _replay(signal, candles)
            else:
                detail = "Aucune bougie historique disponible sur la fenetre"

        r_multiple = _r_multiple(signal, exit_price)
        if outcome is BacktestOutcome.AMBIGUOUS:
            # Hypothese prudente assumee : le pire scenario est retenu.
            r_multiple = AMBIGUOUS_R
        if outcome in (BacktestOutcome.WIN, BacktestOutcome.LOSS, BacktestOutcome.AMBIGUOUS):
            value = r_multiple if r_multiple is not None else 0.0
            total_r += value
            cumulative += value
            curve.append(cumulative)
            decided += 1

        counts[outcome] += 1
        session.add(
            BacktestResult(
                analysis_id=analysis_id,
                channel_id=channel_id,
                message_id=signal.message_id,
                signal_date=signal.date,
                symbol=signal.symbol,
                direction=signal.direction,
                entry_price=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                outcome=outcome,
                r_multiple=r_multiple,
                detail=detail[:255],
            )
        )
    await session.flush()

    average_r = round(total_r / decided, 3) if decided else None
    return {
        "testable": len(tested),
        "wins": counts[BacktestOutcome.WIN],
        "losses": counts[BacktestOutcome.LOSS],
        "ambiguous": counts[BacktestOutcome.AMBIGUOUS],
        "undetermined": counts[BacktestOutcome.UNDETERMINED],
        "open": counts[BacktestOutcome.OPEN],
        "averageR": average_r,
        "totalR": round(total_r, 3),
        "theoreticalDrawdownR": _drawdown(curve),
        "tp1Hits": counts[BacktestOutcome.WIN],
        "slHits": counts[BacktestOutcome.LOSS],
        "disclaimer": DISCLAIMER,
    }
