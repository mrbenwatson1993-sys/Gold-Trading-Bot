"""The candidate config, split by era.

One fixed parameter set applied unchanged to every market: lines drawn on the
daily, weekly and monthly and projected down, three touches, stop trailing
0.25 ATR from the line, gap-calibrated, always in.

Every promising result in this project has died out of sample, so the only
question that matters is whether this one holds when the years are split.
"""
from dataclasses import replace
from datetime import datetime, timezone

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("S&P", "data/spx500_4h.csv", "MES"),
           ("GBPUSD", "data/gbpusd_4h.csv", "M6B"),
           ("EURUSD", "data/eurusd_4h.csv", "M6E"),
           ("SILVER", "data/silver_4h.csv", "SIL")]
ERAS = [("2007-2011", "2007-01-01", "2011-12-31"),
        ("2012-2016", "2012-01-01", "2016-12-31"),
        ("2017-2023", "2017-01-01", "2023-12-31")]


def config(cs):
    return replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", exit_on_stop_only=True,
                   stop_follows_safety=True, safety_line_redraw=False,
                   stop_on_close_only=False, stop_close_confirm_in_profit=True,
                   swing_strength=3, safety_swing_strength=12,
                   line_timeframes=("1d", "1w", "1M"), min_touches=3,
                   max_touches=99, trail_buffer_atr=0.25)


print(f"  {'market':<7} {'era':<11} {'n':>5} {'win%':>6} {'expR':>8} {'PF':>6} "
      f"{'ret%':>8} {'DD%':>6}", flush=True)
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    cfg = config(cs)
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    for era, a, b in ERAS:
        lo = datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp()
        hi = datetime.fromisoformat(b).replace(tzinfo=timezone.utc).timestamp()
        seg = [c for c in cs if lo <= c.ts <= hi]
        if len(seg) < 2000:
            print(f"  {name:<7} {era:<11}  -- too little data", flush=True)
            continue
        s = run(seg, cfg, risk).stats
        if not s.get("trades"):
            print(f"  {name:<7} {era:<11}  -- no trades", flush=True); continue
        print(f"  {name:<7} {era:<11} {s['trades']:>5} {s['win_rate']:>6.1f} "
              f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
              f"{s['return_pct']:>+8.1f} {s['max_drawdown_pct']:>6.1f}", flush=True)
    s = run(cs, cfg, risk).stats
    print(f"  {name:<7} {'ALL':<11} {s['trades']:>5} {s['win_rate']:>6.1f} "
          f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
          f"{s['return_pct']:>+8.1f} {s['max_drawdown_pct']:>6.1f}\n", flush=True)
