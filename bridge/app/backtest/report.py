"""Juge un rejeu : ce qui gagne sur une periode que le reglage n'a jamais vue.

La periode est coupee en deux par une date unique. La premiere partie
(« apprentissage ») sert a choisir ; la seconde (« validation ») sert a
verifier. Une regle n'est retenue que si elle gagne sur LES DEUX, avec assez
de trades en validation pour que ce ne soit pas une coincidence.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

# En dessous, une moyenne positive en validation est trop souvent du hasard.
MIN_VALIDATION_TRADES = 30


@dataclass(slots=True)
class Stats:
    trades: int = 0
    total_r: float = 0.0
    mean_r: float = 0.0
    win_rate: float = 0.0
    profit_factor: float | None = None
    max_drawdown_r: float = 0.0
    t_stat: float | None = None
    runners: int = 0  # trades a plus de 2,5 R

    def line(self) -> str:
        pf = f"{self.profit_factor:5.2f}" if self.profit_factor is not None else "   - "
        t = f"{self.t_stat:+5.2f}" if self.t_stat is not None else "   - "
        return (
            f"{self.trades:5d} trades  {self.mean_r:+6.3f} R/trade  {self.total_r:+8.2f} R  "
            f"gagnants {self.win_rate * 100:4.0f} %  PF {pf}  DD {self.max_drawdown_r:6.2f} R  "
            f"t {t}  runners {self.runners}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "totalR": round(self.total_r, 2),
            "meanR": round(self.mean_r, 4),
            "winRate": round(self.win_rate, 3),
            "profitFactor": round(self.profit_factor, 3) if self.profit_factor else None,
            "maxDrawdownR": round(self.max_drawdown_r, 2),
            "tStat": round(self.t_stat, 2) if self.t_stat is not None else None,
            "runners": self.runners,
        }


def stats(results: Iterable[float]) -> Stats:
    values = list(results)
    out = Stats(trades=len(values))
    if not values:
        return out
    out.total_r = sum(values)
    out.mean_r = out.total_r / len(values)
    out.win_rate = sum(1 for v in values if v > 0.05) / len(values)
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    out.profit_factor = gains / losses if losses > 0 else None
    out.runners = sum(1 for v in values if v >= 2.5)
    peak = equity = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        out.max_drawdown_r = max(out.max_drawdown_r, peak - equity)
    if len(values) > 1:
        var = sum((v - out.mean_r) ** 2 for v in values) / (len(values) - 1)
        if var > 0:
            out.t_stat = out.mean_r / math.sqrt(var / len(values))
    return out


def _filled(rows: list[dict[str, Any]], policy: str) -> list[dict[str, Any]]:
    key = f"{policy.lower()}_filled"
    return sorted((r for r in rows if r.get(key)), key=lambda r: r["time"])


def split_date(rows: list[dict[str, Any]], share: float = 0.7) -> str:
    times = sorted(r["time"] for r in rows)
    return times[int(len(times) * share)] if times else ""


def _band(score: float) -> str:
    low = int(score // 5 * 5)
    return f"{low}-{low + 5}"


GROUPS: dict[str, Callable[[dict[str, Any]], str]] = {
    "instrument": lambda r: r["symbol"],
    "score technique": lambda r: _band(r["raw_score"]),
    "type d'entree": lambda r: r["entry_type"],
    "sens": lambda r: r["direction"],
    "TP1 / risque": lambda r: "TP1 <= 1,2 R" if (r["first_rr"] or 0) <= 1.2 else "TP1 > 1,2 R",
}


def judge(rows: list[dict[str, Any]], policy: str = "LADDER") -> dict[str, Any]:
    """Statistiques apprentissage / validation, globales et par groupe."""
    filled = _filled(rows, policy)
    cut = split_date(filled)
    r_key = f"{policy.lower()}_r"

    def halves(subset: list[dict[str, Any]]) -> tuple[Stats, Stats]:
        return (
            stats(r[r_key] for r in subset if r["time"] < cut),
            stats(r[r_key] for r in subset if r["time"] >= cut),
        )

    learn, valid = halves(filled)
    report: dict[str, Any] = {
        "policy": policy,
        "split": cut,
        "first": filled[0]["time"] if filled else None,
        "last": filled[-1]["time"] if filled else None,
        "overall": {"learning": learn, "validation": valid},
        "groups": {},
        "validated": [],
    }
    for name, key in GROUPS.items():
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in filled:
            buckets.setdefault(key(row), []).append(row)
        report["groups"][name] = {}
        for label, subset in sorted(buckets.items()):
            a, b = halves(subset)
            report["groups"][name][label] = {"learning": a, "validation": b}
            if (
                a.mean_r > 0
                and b.mean_r > 0
                and b.trades >= MIN_VALIDATION_TRADES
                and (b.t_stat or 0) > 1.0
            ):
                report["validated"].append(f"{name} = {label}")
    return report


def render(report: dict[str, Any]) -> str:
    lines = [
        f"=== Gestion {report['policy']} — du {report['first']} au {report['last']}",
        f"    coupure apprentissage / validation : {report['split']}",
        "",
        f"  ENSEMBLE  apprentissage  {report['overall']['learning'].line()}",
        f"            validation     {report['overall']['validation'].line()}",
    ]
    for name, buckets in report["groups"].items():
        lines.append("")
        lines.append(f"  par {name}")
        for label, halves in buckets.items():
            lines.append(f"    {label:<14} appr. {halves['learning'].line()}")
            lines.append(f"    {'':<14} valid {halves['validation'].line()}")
    lines.append("")
    if report["validated"]:
        lines.append("  VALIDE (gagne sur les deux periodes, >= "
                     f"{MIN_VALIDATION_TRADES} trades en validation, t > 1) :")
        lines.extend(f"    - {item}" for item in report["validated"])
    else:
        lines.append("  AUCUN groupe ne gagne a la fois en apprentissage et en validation.")
    return "\n".join(lines)


__all__ = ["MIN_VALIDATION_TRADES", "Stats", "judge", "render", "split_date", "stats"]
