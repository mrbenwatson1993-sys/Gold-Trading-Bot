"""The best configuration found on real GC futures, checked per regime.

Swing strength turned out to dominate everything else. At strength 2 the
detector calls every wiggle a pivot and the strategy loses badly; at 5 it
only marks structure a person would draw, and the method works. Every
top-ten configuration uses 5; every bottom configuration uses 2.
"""
from dataclasses import replace
from datetime import datetime, timezone

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
cs, _ = validate(load_csv("data/GC_futures_daily.csv"))
BEST = replace(simple().for_timeframe(bar_seconds(cs)),
               always_in=True, swing_strength=5, min_age_bars=40,
               min_touches=3, max_touches=99, htf_align="soft",
               htf_timeframes=("1w", "1M"))

def seg(a, b):
    lo = datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp()
    hi = datetime.fromisoformat(b).replace(tzinfo=timezone.utc).timestamp()
    return [c for c in cs if lo <= c.ts <= hi]

print("GC daily, always-in, swing 5, 3+ touches, soft HTF agreement\n")
print(f"  {'window':<14} {'n':>4} {'win%':>6} {'expR':>8} {'PF':>6} {'avgW':>7} "
      f"{'ret%':>7} {'DD%':>6} {'B&H%':>7}")
for name, a, b in (("bull 08-11", "2008-10-01", "2011-09-06"),
                   ("bear 11-15", "2011-09-06", "2015-12-17"),
                   ("range 16-18", "2015-12-17", "2018-12-31"),
                   ("1st half", "2008-10-01", "2013-12-31"),
                   ("2nd half", "2014-01-01", "2018-12-31"),
                   ("ALL", "2008-10-01", "2018-12-31")):
    data = seg(a, b)
    if len(data) < 150:
        continue
    bh = (data[-1].close / data[0].close - 1) * 100
    s = run(data, BEST, RISK).stats
    if not s.get("trades"):
        print(f"  {name:<14}  -- no trades"); continue
    print(f"  {name:<14} {s['trades']:>4} {s['win_rate']:>6.1f} "
          f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
          f"{s['avg_win_r']:>+7.2f} {s['return_pct']:>+7.1f} "
          f"{s['max_drawdown_pct']:>6.1f} {bh:>+7.1f}")

print("\n  swing strength is the whole story:")
for sw in (2, 3, 5, 8):
    s = run(cs, replace(BEST, swing_strength=sw), RISK).stats
    print(f"     swing {sw}: n={s['trades']:>4} {s['expectancy_r']:>+.3f}R "
          f"PF {s['profit_factor']:.2f}  ret {s['return_pct']:+.1f}%")

print("\n  cost sensitivity at the best config:")
for slip in (0.0, 1.0, 2.0, 4.0):
    s = run(cs, BEST, replace(RISK, slippage_ticks=slip)).stats
    print(f"     {slip:.0f} ticks: {s['return_pct']:+.1f}%  PF {s['profit_factor']:.2f}")
