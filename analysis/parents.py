"""Should the alignment timeframes be adjacent to the trading one?

Daily+weekly is the right parent pair for a 4H trade. For a 15-minute trade the
weekly is 672x slower -- it cannot inform anything over the trade's lifetime.
Test the fixed (1d,1w) pair against the two timeframes immediately above
whatever is being traded.
"""
from dataclasses import replace
from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
ADJACENT = {"5m": ("15m", "1h"), "15m": ("1h", "4h"),
            "1h": ("4h", "1d"), "4h": ("1d", "1w")}

import sys
for path in sys.argv[1:]:
    cs = load_csv(path)
    bs = bar_seconds(cs)
    tf = timeframe_name(bs)
    base = replace(simple().for_timeframe(bs), always_in=False)
    print(f"\n{tf}  {len(cs)} bars  ({cs[0].dt:%Y-%m-%d}..{cs[-1].dt:%Y-%m-%d})")
    print(f"  {'parents':<14} {'touches':<10} {'htf':<9} {'n':>4} {'expR':>8} "
          f"{'PF':>6} {'ret%':>7} {'DD%':>6}")
    for pname, parents in (("1d+1w fixed", ("1d", "1w")),
                           ("/".join(ADJACENT[tf]), ADJACENT[tf])):
        for tlabel, lo, hi in (("any 2+", 2, 99), ("exactly 3", 3, 3)):
            for align in ("none", "soft", "majority"):
                cfg = replace(base, min_touches=lo, max_touches=hi,
                              htf_align=align, htf_timeframes=parents)
                s = run(cs, cfg, RISK).stats
                if not s.get("trades"):
                    print(f"  {pname:<14} {tlabel:<10} {align:<9}   -- none")
                    continue
                print(f"  {pname:<14} {tlabel:<10} {align:<9} {s['trades']:>4} "
                      f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
                      f"{s['return_pct']:>+7.1f} {s['max_drawdown_pct']:>6.1f}")
        print()
