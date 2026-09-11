"""16 years of 4-hour gold -- the timeframe the strategy's best result lives on.

Everything earlier on 4H used 18 months inside one bull market. This is
2007-2023: the 2008 crash, the 2011 top, the 2011-2015 bear, the 2016-2019
range, the 2020 COVID spike and the 2022 rate shock.
"""
import sys
from dataclasses import replace
from datetime import datetime, timezone

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
cs, rep = validate(load_csv("data/gold_4h_16y.csv"))
base = replace(simple().for_timeframe(bar_seconds(cs)), htf_timeframes=("1d", "1w"))
print(f"{len(cs)} bars  {cs[0].dt:%Y-%m-%d}..{cs[-1].dt:%Y-%m-%d}  "
      f"integrity {rep['pct']:.2f}% bad\n", flush=True)

def line(tag, cfg, data=cs, bh=None):
    s = run(data, cfg, RISK).stats
    if not s.get("trades"):
        return f"  {tag:<34}  -- no trades"
    extra = f" {bh:>+7.1f}" if bh is not None else ""
    return (f"  {tag:<34} {s['trades']:>5} {s['win_rate']:>6.1f} "
            f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
            f"{s['return_pct']:>+8.1f} {s['max_drawdown_pct']:>6.1f}{extra}")

HDR = (f"  {'config':<34} {'n':>5} {'win%':>6} {'expR':>8} {'PF':>6} "
       f"{'ret%':>8} {'DD%':>6}")

print("SWING STRENGTH (always-in, 3+ touches, soft agreement)", flush=True)
print(HDR, flush=True)
for sw in (2, 3, 5, 8, 12):
    cfg = replace(base, always_in=True, swing_strength=sw, min_touches=3,
                  htf_align="soft")
    print(line(f"swing {sw}", cfg), flush=True)

print("\nTOUCH COUNT x AGREEMENT (always-in, swing 5)", flush=True)
print(HDR, flush=True)
for tlabel, lo, hi in (("any 2+", 2, 99), ("3 only", 3, 3), ("3+", 3, 99)):
    for align in ("none", "soft", "majority"):
        cfg = replace(base, always_in=True, swing_strength=5, min_touches=lo,
                      max_touches=hi, htf_align=align)
        print(line(f"{tlabel}, htf={align}", cfg), flush=True)

print("\nFLAT vs ALWAYS-IN (swing 5, 3+ touches, soft)", flush=True)
print(HDR, flush=True)
for always in (False, True):
    cfg = replace(base, always_in=always, swing_strength=5, min_touches=3,
                  htf_align="soft")
    print(line("always-in" if always else "flat", cfg), flush=True)

print("\nOUT OF SAMPLE, by era (best config)", flush=True)
print(HDR + "   B&H%", flush=True)
BEST = replace(base, always_in=True, swing_strength=5, min_touches=3,
               htf_align="soft")
eras = [("2007-2010", "2007-01-01", "2010-12-31"),
        ("2011-2014", "2011-01-01", "2014-12-31"),
        ("2015-2018", "2015-01-01", "2018-12-31"),
        ("2019-2023", "2019-01-01", "2023-12-31")]
for name, a, b in eras:
    lo = datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp()
    hi = datetime.fromisoformat(b).replace(tzinfo=timezone.utc).timestamp()
    seg = [c for c in cs if lo <= c.ts <= hi]
    if len(seg) < 500:
        continue
    print(line(name, BEST, seg, (seg[-1].close/seg[0].close-1)*100), flush=True)
print(line("ALL 2007-2023", BEST, cs, (cs[-1].close/cs[0].close-1)*100), flush=True)
