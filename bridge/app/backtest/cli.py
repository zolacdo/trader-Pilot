"""Ligne de commande du backtest, lancee par ``python -m app.backtest``.

    python -m app.backtest download              # met l'historique MT5 en cache
    python -m app.backtest run --jobs 2          # rejoue et juge
    python -m app.backtest report <dossier>      # rejuge un rejeu deja fait

Les resultats vont dans ``bridge/data/backtest/results/<horodatage>`` :
``trades.csv`` (un signal par ligne), ``report.txt`` et ``report.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.backtest import history
from app.backtest.market import HistoricalMarket
from app.backtest.replay import replay_symbol
from app.backtest.report import judge, render
from app.models.intelligence import Timeframe
from app.watcher.config import WatcherConfig

# Les instruments du watcher, sous leur nom chez Exness.
DEFAULT_SYMBOLS = [
    "BTCUSDm", "XAUUSDm", "EURUSDm", "GBPUSDm", "USDJPYm",
    "ETHUSDm", "US30m", "USTECm", "US500m",
]
FRAMES = [Timeframe.M5, Timeframe.M15, Timeframe.M30, Timeframe.H1, Timeframe.H4, Timeframe.D1]
POLICIES = ("LADDER", "FIRST_TARGET", "LAST_TARGET")


async def _live_config() -> WatcherConfig:
    """Reglages reels du watcher (YAML puis base). Defauts si la base est muette."""
    try:
        from app.database.session import session_scope
        from app.watcher.config import load_config

        async with session_scope() as session:
            return await load_config(session, refresh=True)
    except Exception as exc:  # base arretee : le rejeu reste possible
        print(f"Base inaccessible ({exc}) : reglages par defaut du watcher.", file=sys.stderr)
        return WatcherConfig()


def _progress(symbol: str, done: int, total: int) -> None:
    print(f"  {symbol} {done}/{total}", flush=True)


def _replay_one(symbol: str, config: WatcherConfig, start: str | None, end: str | None,
                step: int) -> list[dict[str, Any]]:
    frames = {}
    for frame in FRAMES:
        rates = history.load_rates(symbol, frame)
        if rates is not None:
            frames[frame] = rates
    info = history.load_symbol_info(symbol)
    if Timeframe.M5 not in frames or info is None:
        print(f"{symbol} : historique absent, lancer d'abord « download ».", flush=True)
        return []
    market = HistoricalMarket(symbol, frames, info)
    base_times = frames[Timeframe.M5]["time"]
    # Laisse 300 bougies M5 de chauffe : les autres unites remontent plus loin.
    first = datetime.fromtimestamp(int(base_times[min(300, len(base_times) - 1)]), UTC)
    last = datetime.fromtimestamp(int(base_times[-1]), UTC)
    begin = max(first, datetime.fromisoformat(start).replace(tzinfo=UTC)) if start else first
    finish = min(last, datetime.fromisoformat(end).replace(tzinfo=UTC)) if end else last
    started = time.monotonic()
    candidates = asyncio.run(replay_symbol(market, config, begin, finish, step, _progress))
    print(f"{symbol} : {len(candidates)} signaux en {time.monotonic() - started:.0f} s", flush=True)
    return [c.row() for c in candidates]


def _write(folder: Path, rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    if rows:
        fields = sorted({key for row in rows for key in row}, key=lambda k: (k not in rows[0], k))
        with (folder / "trades.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    reports = [judge(rows, policy) for policy in POLICIES]
    text = "\n\n".join(render(r) for r in reports)
    (folder / "report.txt").write_text(text, encoding="utf-8")

    def plain(value: Any) -> Any:
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        if isinstance(value, list):
            return [plain(v) for v in value]
        return value

    (folder / "report.json").write_text(
        json.dumps({"meta": meta, "reports": plain(reports)}, indent=2), encoding="utf-8"
    )
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.backtest")
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="met l'historique MT5 en cache")
    dl.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)

    run = sub.add_parser("run", help="rejoue le watcher et juge le resultat")
    run.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    run.add_argument("--start", help="date ISO de debut (defaut : tout l'historique M5)")
    run.add_argument("--end", help="date ISO de fin")
    run.add_argument("--step", type=int, default=15, help="pas de decision, en minutes")
    run.add_argument("--jobs", type=int, default=2, help="instruments rejoues en parallele")

    rep = sub.add_parser("report", help="rejuge un rejeu deja fait")
    rep.add_argument("folder", type=Path)

    args = parser.parse_args(argv)
    if args.command == "download":
        for line in history.download(args.symbols, FRAMES):
            print(line, flush=True)
        return 0

    if args.command == "report":
        with (args.folder / "trades.csv").open(encoding="utf-8") as handle:
            rows = [_typed(row) for row in csv.DictReader(handle)]
        print(_write(args.folder, rows, {"rejudged": datetime.now(UTC).isoformat()}))
        return 0

    config = asyncio.run(_live_config())
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    folder = history.CACHE_DIR / "results" / stamp
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [
            pool.submit(_replay_one, symbol, config, args.start, args.end, args.step)
            for symbol in args.symbols
        ]
        for future in futures:
            rows.extend(future.result())
    meta = {
        "symbols": args.symbols,
        "step": args.step,
        "config": {k: v for k, v in asdict(config).items() if not isinstance(v, (dict, list))},
    }
    print(_write(folder, rows, meta))
    print(f"\nResultats : {folder}")
    return 0


def _typed(row: dict[str, str]) -> dict[str, Any]:
    """Relit une ligne CSV avec ses types."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        if value in ("True", "False"):
            out[key] = value == "True"
        elif value == "":
            out[key] = None
        else:
            try:
                out[key] = float(value) if key not in ("time",) else value
            except ValueError:
                out[key] = value
    return out

