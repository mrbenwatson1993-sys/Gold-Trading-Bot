"""Command line entry point.

    python -m tori scan     data/gold_4h.csv --symbol MGC
    python -m tori backtest data/gold_4h.csv --symbol MGC --risk 1.0
    python -m tori signals  data/gold_4h.csv --min-grade A
    python -m tori fetch    --interval 4h --out data/gold_4h.csv
"""

from __future__ import annotations

import argparse
import sys

from .backtest import run
from .candles import atr_series, bar_seconds, load_csv, timeframe_name
from dataclasses import replace

from .config import RiskConfig, StrategyConfig
from .contracts import REGISTRY, get_contract
from .mtf import build_ladder, find_apexes
from .report import backtest_report, ladder_report, signal_report
from .strategy import ToriStrategy


def _strategy_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("csv", help="OHLC csv (time,open,high,low,close[,volume])")
    p.add_argument("--min-grade", default="F", choices=["F", "C", "B", "A", "A+"],
                   help="lowest grade to act on; F (default) never blocks")
    p.add_argument("--filtered", action="store_true",
                   help="enable the optional quality filters (off by default)")
    p.add_argument("--touches", type=int, default=2,
                   help="minimum touches for a line to exist at all")
    p.add_argument("--swing", type=int, default=3, help="swing strength in bars")
    p.add_argument("--age", type=int, default=60,
                   help="minimum line age in BARS (timeframe-agnostic)")
    p.add_argument("--gap", type=int, default=6, help="min bars between touches")
    p.add_argument("--entry", default="next_open", choices=["next_open", "close"])
    p.add_argument("--trending-only", action="store_true",
                   help="skip setups while structure is ranging")


def _build_cfg(args, candles) -> StrategyConfig:
    from .config import simple
    base = StrategyConfig() if getattr(args, "filtered", False) else simple()
    cfg = replace(
        base,
        swing_strength=args.swing, min_touches=args.touches,
        min_touch_gap_bars=args.gap, min_age_bars=args.age,
        entry_mode=args.entry, min_grade=args.min_grade,
        require_trending_htf=getattr(args, "trending_only", False),
    )
    bs = bar_seconds(candles)
    return cfg.for_timeframe(bs) if bs else cfg


def cmd_scan(args) -> int:
    """Where are we right now? The top-down read plus any live coil."""
    candles = load_csv(args.csv)
    cfg = _build_cfg(args, candles)
    atr = atr_series(candles, cfg.atr_period)
    i = len(candles) - 1

    views = build_ladder(candles, cfg, i)
    apexes = find_apexes(views, candles[i], atr[i], cfg)
    print(ladder_report(views, apexes, candles[i], cfg.bar_seconds))

    strat = ToriStrategy(candles, atr, cfg)
    signal = strat.find_signal(i - 1)   # the last fully-formed bar
    if signal is not None:
        print()
        print("  *** BREAK ON THE LAST CLOSED BAR ***")
        print(signal_report(signal))
    return 0


def cmd_signals(args) -> int:
    """Every graded break in the file -- the setup log."""
    candles = load_csv(args.csv)
    cfg = _build_cfg(args, candles)
    atr = atr_series(candles, cfg.atr_period)
    strat = ToriStrategy(candles, atr, cfg)

    count = 0
    warmup = max(cfg.atr_period + cfg.swing_strength * 2, cfg.min_age_bars) + 5
    for i in range(warmup, len(candles) - 1):
        signal = strat.find_signal(i)
        if signal is None:
            strat.observe(i)
            continue
        count += 1
        if not args.quiet:
            print(signal_report(signal))
            print()
    print(f"{count} setups at grade {cfg.min_grade} or better "
          f"over {len(candles)} bars ({timeframe_name(cfg.bar_seconds)})")
    return 0


def cmd_backtest(args) -> int:
    candles = load_csv(args.csv)
    cfg = _build_cfg(args, candles)
    risk = RiskConfig(
        symbol=args.symbol, starting_equity=args.equity, risk_pct=args.risk,
        slippage_ticks=args.slippage, allow_longs=not args.shorts_only,
        allow_shorts=not args.longs_only,
    )
    result = run(candles, cfg, risk)
    print(backtest_report(result, show_trades=not args.quiet))
    return 0


def cmd_fetch(args) -> int:
    from .fetch import main as fetch_main
    return fetch_main(["--pair", args.pair, "--interval", args.interval,
                       "--bars", str(args.bars), "--out", args.out])


def cmd_contracts(args) -> int:
    print(f"  {'sym':<5} {'name':<26} {'tick':>9} {'$/tick':>8} {'$/point':>9}")
    for c in REGISTRY.values():
        print(f"  {c.symbol:<5} {c.name:<26} {c.tick_size:>9} "
              f"{c.tick_value:>8.2f} {c.point_value:>9,.0f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tori", description="Tori Trades trendline strategy")
    subs = p.add_subparsers(dest="cmd", required=True)

    s = subs.add_parser("scan", help="top-down read + live coils, right now")
    _strategy_args(s)
    s.set_defaults(func=cmd_scan)

    s = subs.add_parser("signals", help="log every graded break in the file")
    _strategy_args(s)
    s.add_argument("--quiet", action="store_true", help="count only")
    s.set_defaults(func=cmd_signals)

    s = subs.add_parser("backtest", help="run the strategy over the file")
    _strategy_args(s)
    s.add_argument("--symbol", default="MGC", help="futures contract (see 'contracts')")
    s.add_argument("--equity", type=float, default=25_000.0)
    s.add_argument("--risk", type=float, default=1.0, help="%% of equity per trade")
    s.add_argument("--slippage", type=float, default=1.0, help="ticks per fill")
    s.add_argument("--longs-only", action="store_true")
    s.add_argument("--shorts-only", action="store_true")
    s.add_argument("--quiet", action="store_true", help="summary only")
    s.set_defaults(func=cmd_backtest)

    s = subs.add_parser("fetch", help="download development candles")
    s.add_argument("--pair", default="PAXG_USDT")
    s.add_argument("--interval", default="4h")
    s.add_argument("--bars", type=int, default=9000)
    s.add_argument("--out", default="data/gold_4h.csv")
    s.set_defaults(func=cmd_fetch)

    s = subs.add_parser("contracts", help="list known futures contracts")
    s.set_defaults(func=cmd_contracts)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
