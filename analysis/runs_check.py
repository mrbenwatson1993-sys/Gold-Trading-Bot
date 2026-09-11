"""Does the trade run until structure breaks, or until the stop clips it?

Price is supposed to decide the profit: the trade ends when price breaks back
through the line, which might be 1R or 30R. If almost nothing ever reaches 3R
the line is being drawn through noise, and the stop -- not price -- is setting
the profit. This measures where the profits actually land as the Safety Line
is read at coarser and coarser structure.
"""
from dataclasses import replace
from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
cs, _ = validate(load_csv("data/gold_4h_16y.csv"))
base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
               htf_align="none", stop_follows_safety=True,
               stop_on_close_only=False, swing_strength=3,
               min_touches=3, max_touches=99)

print("  safety line read at strength S (trendline detection stays at 3)\n")
print(f"  {'S':>3} {'n':>5} {'hold':>6} {'days':>5} {'expR':>8} {'PF':>6} "
      f"{'avgW':>7} {'best':>7} | {'>=2R':>6} {'>=3R':>6} {'>=5R':>6} "
      f"{'>=10R':>6} | {'ret%':>9} {'DD%':>6}")
for sw in (3, 5, 8, 12, 16, 24):
    r = run(cs, replace(base, safety_swing_strength=sw), RISK)
    s = r.stats
    if not s.get("trades"):
        print(f"  {sw:>3}   no trades"); continue
    ts = r.trades
    rs = [t.r_multiple for t in ts]
    n = len(ts)
    pc = lambda x: f"{sum(1 for v in rs if v >= x)/n*100:>5.1f}%"
    hold = sum(t.exit_index - t.entry_index for t in ts) / n
    print(f"  {sw:>3} {n:>5} {hold:>6.1f} {hold*4/24:>5.1f} "
          f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
          f"{s['avg_win_r']:>+7.2f} {max(rs):>+7.1f} | "
          f"{pc(2)} {pc(3)} {pc(5)} {pc(10)} | "
          f"{s['return_pct']:>+9.1f} {s['max_drawdown_pct']:>6.1f}", flush=True)
