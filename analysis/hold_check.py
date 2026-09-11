"""How long does the engine hold, against the ~54 bars the reference chart shows?

In the chart the Safety Line is drawn through major swing lows -- multi-day
pullbacks -- so it sits well below price and the trade breathes for nine days.
Detecting swings at strength 3 on a 4H chart marks every three-bar dip as a
higher low, which makes the line steep and the stop tight. This measures the
effect directly.
"""
from dataclasses import replace
from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
cs, _ = validate(load_csv("data/gold_4h_16y.csv"))
base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
               htf_align="none", stop_follows_safety=True,
               stop_on_close_only=False, min_touches=3, max_touches=99)

print(f"  {'swing':>5} {'n':>5} {'hold':>6} {'days':>6} {'expR':>8} {'PF':>6} "
      f"{'avgW':>7} {'peak':>7} {'kept':>6} {'>=3R':>5} {'ret%':>8} {'DD%':>6}")
for sw in (3, 5, 8, 12, 16, 20):
    cfg = replace(base, swing_strength=sw)
    r = run(cs, cfg, RISK)
    s = r.stats
    if not s.get("trades"):
        print(f"  {sw:>5}   no trades"); continue
    ts = r.trades
    hold = sum(t.exit_index - t.entry_index for t in ts) / len(ts)
    peak = sum(t.mfe_r for t in ts) / len(ts)
    kept = (s["expectancy_r"] / peak * 100) if peak > 0 else 0
    over3 = sum(1 for t in ts if t.r_multiple >= 3)
    print(f"  {sw:>5} {s['trades']:>5} {hold:>6.1f} {hold*4/24:>6.1f} "
          f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
          f"{s['avg_win_r']:>+7.2f} {peak:>+7.2f} {kept:>5.0f}% "
          f"{over3:>5} {s['return_pct']:>+8.1f} {s['max_drawdown_pct']:>6.1f}",
          flush=True)
print("\n  reference chart: entry 20 May, exit 29 May ~= 54 bars / 9 days")
