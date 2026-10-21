"""Deroule un trade sur des bougies historiques, sans jamais deviner en sa faveur.

Les bougies MT5 sont cotees au bid. Un achat entre donc au ask (bid + spread)
et sort au bid ; une vente entre au bid et sort au ask. Le spread est celui de
chaque bougie, pas une moyenne.

Quand une meme bougie touche le stop ET un objectif, on ne sait pas lequel est
venu en premier : le stop l'emporte, toujours. Un backtest qui tranche ces cas
en sa faveur fabrique un avantage qui n'existe pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class ExitPolicy(StrEnum):
    """Facon de sortir, une fois l'entree faite."""

    # Gestion reelle du compte depuis le 30/09/2026 : tout le volume vise le
    # dernier objectif, et le stop monte d'un cran a chaque objectif franchi
    # (TP1 -> entree, TP2 -> TP1, ...).
    LADDER = "LADDER"
    # Tout sortir au premier objectif.
    FIRST_TARGET = "FIRST_TARGET"
    # Viser le dernier objectif sans jamais bouger le stop.
    LAST_TARGET = "LAST_TARGET"


@dataclass(slots=True)
class Bars:
    """Bougies d'execution (M5 en pratique), en tableaux paralleles."""

    time: np.ndarray  # debut de bougie, secondes epoch
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    spread: np.ndarray  # en points
    point: float
    seconds: int  # duree d'une bougie

    def __len__(self) -> int:
        return len(self.time)


@dataclass(slots=True)
class TradeResult:
    filled: bool
    exit_reason: str
    entry_time: int | None = None
    entry_price: float | None = None
    exit_time: int | None = None
    exit_price: float | None = None
    r: float = 0.0
    max_favorable_r: float = 0.0
    targets_hit: int = 0


def simulate_trade(
    bars: Bars,
    start: int,
    buy: bool,
    entry: float,
    stop: float,
    targets: list[float],
    pending: bool,
    policy: ExitPolicy = ExitPolicy.LADDER,
    pending_minutes: int = 240,
    max_hold_minutes: int = 7 * 24 * 60,
) -> TradeResult:
    """Rejoue un trade a partir de la bougie d'indice ``start``.

    ``start`` est la premiere bougie qui s'ouvre APRES la decision : rien de
    ce qui precede n'est lu. Un ordre au marche est rempli a son ouverture ;
    un ordre stop (``pending``) l'est quand le prix franchit ``entry`` avant
    ``pending_minutes``, sinon il est annule.
    """
    if start >= len(bars) or not targets:
        return TradeResult(filled=False, exit_reason="NO_DATA")
    targets = sorted(targets) if buy else sorted(targets, reverse=True)
    sign = 1.0 if buy else -1.0
    point = bars.point

    # --- entree ------------------------------------------------------------
    fill_index: int | None = None
    fill = 0.0
    deadline = bars.time[start] + pending_minutes * 60
    for i in range(start, len(bars)):
        spread = bars.spread[i] * point
        if not pending:
            fill = bars.open[i] + spread if buy else bars.open[i]
            fill_index = i
            break
        if bars.time[i] >= deadline:
            return TradeResult(filled=False, exit_reason="PENDING_EXPIRED")
        if buy and bars.high[i] + spread >= entry:
            # Un saut d'ouverture au-dela du declenchement remplit plus mal.
            fill = max(entry, bars.open[i] + spread)
            fill_index = i
            break
        if not buy and bars.low[i] <= entry:
            fill = min(entry, bars.open[i])
            fill_index = i
            break
    if fill_index is None:
        return TradeResult(filled=False, exit_reason="NO_DATA")

    risk = (fill - stop) * sign
    if risk <= 0:
        # Le prix a deja depasse le stop au remplissage : aucun courtier
        # n'accepterait cet ordre.
        return TradeResult(filled=False, exit_reason="STOP_BEYOND_FILL")

    result = TradeResult(
        filled=True, exit_reason="", entry_time=int(bars.time[fill_index]), entry_price=fill
    )
    if policy is ExitPolicy.FIRST_TARGET:
        aims = targets[:1]
    else:
        aims = targets
    current_stop = stop
    reached = 0
    limit = bars.time[fill_index] + max_hold_minutes * 60

    # --- vie de la position ----------------------------------------------
    for i in range(fill_index, len(bars)):
        spread = bars.spread[i] * point
        # Prix de sortie atteignables pendant la bougie, du cote qui ferme.
        if buy:
            worst, best = bars.low[i], bars.high[i]
        else:
            worst, best = bars.high[i] + spread, bars.low[i] + spread
        result.max_favorable_r = max(result.max_favorable_r, (best - fill) * sign / risk)

        if (worst - current_stop) * sign <= 0:
            # Un saut d'ouverture au-dela du stop sort plus mal que le stop.
            opening = bars.open[i] if buy else bars.open[i] + spread
            price = min(current_stop, opening) if buy else max(current_stop, opening)
            return _close(result, i, bars, price, fill, risk, sign, reached, "STOP")

        while reached < len(aims) and (best - aims[reached]) * sign >= 0:
            reached += 1
            if reached == len(aims):
                return _close(result, i, bars, aims[-1], fill, risk, sign, reached, "TARGET")
            if policy is ExitPolicy.LADDER:
                current_stop = fill if reached == 1 else aims[reached - 2]

        if bars.time[i] >= limit:
            exit_price = bars.close[i] if buy else bars.close[i] + spread
            return _close(result, i, bars, exit_price, fill, risk, sign, reached, "TIME")

    last = len(bars) - 1
    exit_price = bars.close[last] if buy else bars.close[last] + bars.spread[last] * point
    return _close(result, last, bars, exit_price, fill, risk, sign, reached, "END_OF_DATA")


def _close(
    result: TradeResult,
    index: int,
    bars: Bars,
    price: float,
    fill: float,
    risk: float,
    sign: float,
    reached: int,
    reason: str,
) -> TradeResult:
    result.exit_time = int(bars.time[index]) + bars.seconds
    result.exit_price = float(price)
    result.r = float((price - fill) * sign / risk)
    result.targets_hit = reached
    result.exit_reason = reason
    return result


__all__ = ["Bars", "ExitPolicy", "TradeResult", "simulate_trade"]
