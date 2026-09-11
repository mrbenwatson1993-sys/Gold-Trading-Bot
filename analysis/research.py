"""Deep grid: touch count x higher-timeframe alignment, per timeframe.

Runs in "flat between setups" mode deliberately. Always-in confounds the
question, because each reversal inherits its touch count from the Safety Line
that just broke rather than from a line that was tested three times.
"""

from __future__ import annotations

import sys
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
TOUCHES = [("any 2+", 2, 99), ("exactly 2", 2, 2), ("exactly 3", 3, 3),
           ("exactly 4", 4, 4), ("5 or more", 5, 99)]
ALIGN = ["none", "soft", "majority", "all"]

HDR = (f"  {'touches':<10} {'htf':<9} {'n':>5} {'win%':>6} {'expR':>8} {'PF':>6} "
       f"{'RR':>5} {'>=3R':>5} {'ret%':>8} {'DD%':>6} {'L/S':>9} {'skip':>5}")


def row(label, align, r):
    s = r.stats
    if not s.get("trades"):
        return f"  {label:<10} {align:<9}     -- no trades"
    ts = r.trades
    rs = [t.r_multiple for t in ts]
    wins = [v for v in rs if v > 0]
    losses = [v for v in rs if v <= 0]
    rr = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else 0
    d = s["by_direction"]
    ls = f"{d.get('long',{}).get('n',0)}/{d.get('short',{}).get('n',0)}"
    return (f"  {label:<10} {align:<9} {s['trades']:>5} {s['win_rate']:>6.1f} "
            f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} {rr:>5.2f} "
            f"{sum(1 for v in rs if v >= 3):>5} {s['return_pct']:>+8.1f} "
            f"{s['max_drawdown_pct']:>6.1f} {ls:>9} {sum(r.skipped.values()):>5}")


def main(paths):
    for path in paths:
        candles = load_csv(path)
        bs = bar_seconds(candles)
        base = replace(simple().for_timeframe(bs), always_in=False)
        print(f"\n{'='*104}", flush=True)
        print(f"{timeframe_name(bs)}   {len(candles)} bars   "
              f"{candles[0].dt:%Y-%m-%d} .. {candles[-1].dt:%Y-%m-%d}", flush=True)
        print('='*104, flush=True)
        print(HDR, flush=True)
        for label, lo, hi in TOUCHES:
            for align in ALIGN:
                cfg = replace(base, min_touches=lo, max_touches=hi,
                              htf_align=align)
                print(row(label, align, run(candles, cfg, RISK)), flush=True)
            print(f"  {'-'*100}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or ["data/gold_4h.csv"])
