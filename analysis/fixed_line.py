"""Does freezing the Safety Line let the trade run?

The reference chart draws the green line once, at the entry, and leaves it
there. Price riding above it keeps the trade alive; price crossing back
through it ends the trade. The stop is a safety net just on the far side of
that line, so a cross-back does not hand the profit back.

Redrawing the line to each new higher low instead walks it up towards price
and ends the trade early -- which is what has been capping every winner near
1R. This measures the difference.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("SILVER", "data/silver_4h.csv", "SIL")]

print(f"  {'market':<7} {'line':<8} {'tch':<4} {'n':>5} {'hold':>6} {'days':>5} "
      f"{'expR':>8} {'PF':>6} {'avgW':>7} {'best':>7} {'>=5R':>6} {'>=10R':>6} "
      f"{'ret%':>9} {'DD%':>6}")
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", stop_on_close_only=False,
                   stop_follows_safety=True, swing_strength=3,
                   safety_swing_strength=12)
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    for label, redraw in (("redrawn", True), ("FIXED", False)):
        for tch in (3, 5):
            cfg = replace(base, safety_line_redraw=redraw,
                          min_touches=tch, max_touches=99)
            r = run(cs, cfg, risk)
            s = r.stats
            if not s.get("trades"):
                print(f"  {name:<7} {label:<8} {tch:<4}  -- none"); continue
            ts = r.trades
            rs = [t.r_multiple for t in ts]
            n = len(ts)
            hold = sum(t.exit_index - t.entry_index for t in ts) / n
            pc = lambda x: f"{sum(1 for v in rs if v >= x)/n*100:>5.1f}%"
            print(f"  {name:<7} {label:<8} {tch:<4} {n:>5} {hold:>6.1f} "
                  f"{hold*4/24:>5.1f} {s['expectancy_r']:>+8.3f} "
                  f"{s['profit_factor']:>6.2f} {s['avg_win_r']:>+7.2f} "
                  f"{max(rs):>+7.1f} {pc(5)} {pc(10)} "
                  f"{s['return_pct']:>+9.1f} {s['max_drawdown_pct']:>6.1f}",
                  flush=True)
    print(flush=True)
