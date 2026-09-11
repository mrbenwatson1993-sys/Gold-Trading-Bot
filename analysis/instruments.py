"""Does any of this hold on markets other than gold?

A claim about trendlines should not care what the symbol is. If it only pays
on gold, it is a property of gold.

The series are index/spot CFDs rather than the contracts themselves -- the same
stand-in used for gold, measured there at 0.993 bar-return correlation with GC
futures once timestamps are aligned and the basis removed
(analysis/proxy_check.py). Brent is the weakest substitution: a different crude
from WTI, closely correlated but not the same contract.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [
    ("GOLD   GC/MGC", "data/gold_4h_16y.csv", "MGC"),
    ("S&P    ES/MES", "data/spx500_4h.csv", "MES"),
    ("NASDAQ NQ/MNQ", "data/nas100_4h.csv", "MNQ"),
    ("BRENT  CL/MCL", "data/brent_4h.csv", "MCL"),
    ("SILVER SI/SIL", "data/silver_4h.csv", "SIL"),
]
TOUCHES = [("2", 2, 2), ("3", 3, 3), ("4", 4, 4), ("5", 5, 5), ("2+", 2, 99)]

print(f"  {'market':<14} {'tch':<4} {'n':>5} {'win%':>6} {'expR':>8} {'PF':>6} "
      f"{'avgW':>7} {'best':>7} {'>=3R':>6} {'ret%':>9} {'DD%':>6} {'B&H%':>9}")
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", stop_follows_safety=True,
                   stop_on_close_only=False, swing_strength=3,
                   safety_swing_strength=12)
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    bh = (cs[-1].close / cs[0].close - 1) * 100
    for label, lo, hi in TOUCHES:
        r = run(cs, replace(base, min_touches=lo, max_touches=hi), risk)
        s = r.stats
        if not s.get("trades"):
            print(f"  {name:<14} {label:<4}   -- no trades", flush=True); continue
        rs = [t.r_multiple for t in r.trades]
        over3 = sum(1 for v in rs if v >= 3) / len(rs) * 100
        print(f"  {name:<14} {label:<4} {s['trades']:>5} {s['win_rate']:>6.1f} "
              f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
              f"{s['avg_win_r']:>+7.2f} {max(rs):>+7.1f} {over3:>5.1f}% "
              f"{s['return_pct']:>+9.1f} {s['max_drawdown_pct']:>6.1f} "
              f"{bh:>+9.1f}", flush=True)
    print(flush=True)
