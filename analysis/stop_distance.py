"""How close can the stop sit to the trendline?

The stop follows price on the far side of the line, so that price crossing
back through the line ends the trade. Sitting close makes the exit faithful to
the line; sitting too close means being taken out by a spike while the candle
itself closes back on the correct side -- structure never broke, and the trade
was ended by noise.

"wick%" is the share of exits where exactly that happened: the stop was hit
intrabar, and that same candle closed back on the right side of the line.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("SILVER", "data/silver_4h.csv", "SIL")]
DISTANCES = (0.05, 0.10, 0.25, 0.50, 0.75, 1.00, 1.50)

print(f"  {'market':<7} {'dist':>6} {'n':>5} {'hold':>6} {'wick%':>7} {'expR':>8} "
      f"{'PF':>6} {'avgW':>7} {'best':>7} {'>=5R':>6} {'>=10R':>6} "
      f"{'ret%':>9} {'DD%':>6}")
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", exit_on_stop_only=True,
                   stop_follows_safety=True, stop_on_close_only=False,
                   safety_line_redraw=False, swing_strength=3,
                   safety_swing_strength=12, min_touches=3, max_touches=99)
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    for dist in DISTANCES:
        r = run(cs, replace(base, trail_buffer_atr=dist), risk)
        s = r.stats
        if not s.get("trades"):
            print(f"  {name:<7} {dist:>6.2f}  -- none"); continue
        ts = r.trades
        rs = [t.r_multiple for t in ts]
        n = len(ts)
        wicked = sum(1 for t in ts if t.exit_reason == "stop (wicked)")
        hold = sum(t.exit_index - t.entry_index for t in ts) / n
        pc = lambda x: f"{sum(1 for v in rs if v >= x)/n*100:>5.1f}%"
        print(f"  {name:<7} {dist:>6.2f} {n:>5} {hold:>6.1f} "
              f"{wicked/n*100:>6.1f}% {s['expectancy_r']:>+8.3f} "
              f"{s['profit_factor']:>6.2f} {s['avg_win_r']:>+7.2f} "
              f"{max(rs):>+7.1f} {pc(5)} {pc(10)} "
              f"{s['return_pct']:>+9.1f} {s['max_drawdown_pct']:>6.1f}", flush=True)
    print(flush=True)
