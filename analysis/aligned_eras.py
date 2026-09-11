"""Always-in with the trend, flat against it -- checked era by era.

Every other promising result in this project evaporated out of sample, so the
only number that matters is whether this one holds in each era independently.
"""
from dataclasses import replace
from datetime import datetime, timezone
from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
cs, _ = validate(load_csv("data/gold_4h_16y.csv"))
BEST = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
               swing_strength=5, min_touches=3, htf_align="soft",
               htf_timeframes=("1d", "1w"))

def seg(a, b):
    lo = datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp()
    hi = datetime.fromisoformat(b).replace(tzinfo=timezone.utc).timestamp()
    return [c for c in cs if lo <= c.ts <= hi]

print("always-in with the trend, flat against it (swing 5, 3+ touches, soft)\n")
print(f"  {'era':<12} {'n':>4} {'win%':>6} {'expR':>8} {'PF':>6} {'avgW':>7} "
       f"{'ret%':>7} {'DD%':>6} {'B&H%':>8}", flush=True)
eras = [("2007-2010", "2007-01-01", "2010-12-31"),
        ("2011-2014", "2011-01-01", "2014-12-31"),
        ("2015-2018", "2015-01-01", "2018-12-31"),
        ("2019-2023", "2019-01-01", "2023-12-31")]
for name, a, b in eras:
    d = seg(a, b)
    if len(d) < 500:
        continue
    s = run(d, BEST, RISK).stats
    bh = (d[-1].close / d[0].close - 1) * 100
    if not s.get("trades"):
        print(f"  {name:<12}  -- no trades"); continue
    print(f"  {name:<12} {s['trades']:>4} {s['win_rate']:>6.1f} "
          f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
          f"{s['avg_win_r']:>+7.2f} {s['return_pct']:>+7.1f} "
          f"{s['max_drawdown_pct']:>6.1f} {bh:>+8.1f}", flush=True)
s = run(cs, BEST, RISK).stats
print(f"  {'ALL':<12} {s['trades']:>4} {s['win_rate']:>6.1f} "
      f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
      f"{s['avg_win_r']:>+7.2f} {s['return_pct']:>+7.1f} "
      f"{s['max_drawdown_pct']:>6.1f} {(cs[-1].close/cs[0].close-1)*100:>+8.1f}",
      flush=True)

print("\n  cost sensitivity:", flush=True)
for slip in (0.0, 1.0, 2.0, 4.0):
    s = run(cs, BEST, replace(RISK, slippage_ticks=slip)).stats
    print(f"     {slip:.0f} ticks: {s['return_pct']:+7.1f}%  PF {s['profit_factor']:.2f}",
          flush=True)
