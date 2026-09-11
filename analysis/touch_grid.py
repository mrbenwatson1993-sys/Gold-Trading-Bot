"""Touch count, tested exactly as specified.

  * Higher timeframes place the lines accurately (monthly down to 4H); they
    are never a directional veto. htf_align is off.
  * Every trade starts with a fixed stop sized to risk a set % of the account.
  * The stop rides the Safety Line up with price and never moves back, so a
    trade cannot lose more than the risk it was sized for.
  * Always in the market, flipping on each break of the line being ridden.

On touch counts: a straight line needs two points, so two is the geometric
floor -- "0 touches" and "1 touch" cannot define a trendline at all. Both
labellings are shown, so "0 extra beyond the two anchors" is the 2-touch row
and the 3-touch A+ setup from the chart is the "+1 extra" row.
"""
import sys
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name, validate
from tori.config import RiskConfig, simple

TOUCHES = [("2 (0 extra)", 2, 2), ("3 (1 extra)", 3, 3), ("4 (2 extra)", 4, 4),
           ("5 (3 extra)", 5, 5), ("unlimited 2+", 2, 99)]
HDR = (f"  {'touches':<14} {'n':>5} {'win%':>6} {'expR':>8} {'PF':>6} {'avgW':>7} "
       f"{'avgL':>7} {'worst':>7} {'ret%':>9} {'DD%':>6} {'hold':>6}")


def row(label, cfg, cs, risk):
    r = run(cs, cfg, risk)
    s = r.stats
    if not s.get("trades"):
        return f"  {label:<14}   -- no trades"
    ts = r.trades
    rs = [t.r_multiple for t in ts]
    held = sum(t.exit_index - t.entry_index for t in ts) / len(ts)
    return (f"  {label:<14} {s['trades']:>5} {s['win_rate']:>6.1f} "
            f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
            f"{s['avg_win_r']:>+7.2f} {s['avg_loss_r']:>+7.2f} "
            f"{min(rs):>+7.2f} {s['return_pct']:>+9.1f} "
            f"{s['max_drawdown_pct']:>6.1f} {held:>6.1f}")


for path in sys.argv[1:]:
    cs, _ = validate(load_csv(path))
    bs = bar_seconds(cs)
    base = replace(simple().for_timeframe(bs), always_in=True,
                   htf_align="none", stop_follows_safety=True,
                   stop_on_close_only=False, swing_strength=3)
    print(f"\n{'='*108}")
    print(f"{timeframe_name(bs)}  {len(cs)} bars  {cs[0].dt:%Y-%m-%d}..{cs[-1].dt:%Y-%m-%d}"
          f"   no HTF filter | fixed stop, trailing with price | always in")
    print('='*108)
    for pct in (1.0, 2.0):
        risk = RiskConfig(symbol="MGC", starting_equity=250_000, risk_pct=pct)
        print(f"\n  -- risking {pct:.0f}% of the account per trade")
        print(HDR)
        for label, lo, hi in TOUCHES:
            cfg = replace(base, min_touches=lo, max_touches=hi)
            print(row(label, cfg, cs, risk), flush=True)
