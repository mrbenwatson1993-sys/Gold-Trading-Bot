"""The real test: 10 years of COMEX gold futures, three regimes.

Everything before this ran on 18 months of a spot proxy inside one bull
market. This is GC daily from the 2008 low through the 2011 top, the
2011-2015 bear market and the 2016-2018 range -- the regime diversity that
was missing.
"""
from dataclasses import replace
from datetime import datetime, timezone

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
PARENTS = ("1w", "1M")

cs = load_csv("data/GC_futures_daily.csv")
cs, rep = validate(cs)
bs = bar_seconds(cs)
base = replace(simple().for_timeframe(bs), always_in=False,
               htf_timeframes=PARENTS)

print(f"GC daily  {len(cs)} bars  {cs[0].dt:%Y-%m-%d} .. {cs[-1].dt:%Y-%m-%d}")
print(f"data repair: {rep['inconsistent']} bars ({rep['pct']:.1f}%), "
      f"mean {rep['shift_in_atr']:.3f} ATR\n")

REGIMES = [
    ("bull 08-11", "2008-10-01", "2011-09-06"),
    ("bear 11-15", "2011-09-06", "2015-12-17"),
    ("range 16-18", "2015-12-17", "2018-12-31"),
    ("ALL 08-18", "2008-10-01", "2018-12-31"),
]

def seg(a, b):
    lo = datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp()
    hi = datetime.fromisoformat(b).replace(tzinfo=timezone.utc).timestamp()
    return [c for c in cs if lo <= c.ts <= hi]

print(f"  {'regime':<12} {'touches':<10} {'htf':<9} {'n':>4} {'expR':>8} "
      f"{'PF':>6} {'win%':>6} {'ret%':>7} {'DD%':>6} {'B&H%':>7}")
for rname, a, b in REGIMES:
    data = seg(a, b)
    if len(data) < 200:
        continue
    bh = (data[-1].close / data[0].close - 1) * 100
    for tlabel, lo, hi in (("any 2+", 2, 99), ("exactly 3", 3, 3)):
        for align in ("none", "soft", "majority"):
            cfg = replace(base, min_touches=lo, max_touches=hi, htf_align=align)
            s = run(data, cfg, RISK).stats
            if not s.get("trades"):
                print(f"  {rname:<12} {tlabel:<10} {align:<9}   -- no trades")
                continue
            print(f"  {rname:<12} {tlabel:<10} {align:<9} {s['trades']:>4} "
                  f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
                  f"{s['win_rate']:>6.1f} {s['return_pct']:>+7.1f} "
                  f"{s['max_drawdown_pct']:>6.1f} {bh:>+7.1f}")
    print()
