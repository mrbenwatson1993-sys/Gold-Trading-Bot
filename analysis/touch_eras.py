"""Does the touch-count effect hold era by era?

Every other promising result here evaporated out of sample. The touch ladder
is the cleanest signal found, so the only question that matters is whether it
survives being cut into independent periods.
"""
from dataclasses import replace
from datetime import datetime, timezone

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000, risk_pct=1.0)
cs, _ = validate(load_csv("data/gold_4h_16y.csv"))
base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
               htf_align="none", stop_follows_safety=True,
               stop_on_close_only=False, swing_strength=3)

ERAS = [("2007-2010", "2007-01-01", "2010-12-31"),
        ("2011-2014", "2011-01-01", "2014-12-31"),
        ("2015-2018", "2015-01-01", "2018-12-31"),
        ("2019-2023", "2019-01-01", "2023-12-31")]

def seg(a, b):
    lo = datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp()
    hi = datetime.fromisoformat(b).replace(tzinfo=timezone.utc).timestamp()
    return [c for c in cs if lo <= c.ts <= hi]

print("expectancy (R) by touch count, per era -- 1% risk, no HTF filter\n")
print(f"  {'era':<12} {'2 touch':>16} {'3 touch':>16} {'4 touch':>16} {'5 touch':>16}")
for name, a, b in ERAS:
    d = seg(a, b)
    cells = []
    for t in (2, 3, 4, 5):
        s = run(d, replace(base, min_touches=t, max_touches=t), RISK).stats
        cells.append(f"{s['expectancy_r']:+.3f} (n={s['trades']})"
                     if s.get("trades") else "none")
    print(f"  {name:<12} " + " ".join(f"{c:>16}" for c in cells), flush=True)

cells = []
for t in (2, 3, 4, 5):
    s = run(cs, replace(base, min_touches=t, max_touches=t), RISK).stats
    cells.append(f"{s['expectancy_r']:+.3f} (n={s['trades']})")
print(f"  {'ALL':<12} " + " ".join(f"{c:>16}" for c in cells), flush=True)
