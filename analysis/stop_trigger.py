"""Three ways to trigger the trailing stop, and what each costs.

  intrabar  -- the stop always fills on a touch. Risk is capped at what the
               trade was sized for, but a spike can end a winner that
               structure never invalidated.
  hybrid    -- intrabar while the stop is still below entry (the real risk
               cap), close-confirmed once it has trailed to breakeven or
               better. A wick cannot take a winning trade; the worst case on
               that side is giving back open profit.
  close     -- always waits for a close beyond the stop. Kills wick-outs
               entirely and removes the risk cap with them: a bar can drive
               through the level and settle far beyond it.

"worst" is the largest single loss in R. It is the column that says whether
the risk cap survived.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("SILVER", "data/silver_4h.csv", "SIL")]
MODES = [("intrabar", dict(stop_on_close_only=False, stop_close_confirm_in_profit=False)),
         ("hybrid",   dict(stop_on_close_only=False, stop_close_confirm_in_profit=True)),
         ("close",    dict(stop_on_close_only=True,  stop_close_confirm_in_profit=False))]

print(f"  {'market':<7} {'trigger':<9} {'dist':>5} {'n':>5} {'hold':>6} {'wick%':>7} "
      f"{'expR':>8} {'PF':>6} {'avgW':>7} {'worst':>7} {'best':>7} "
      f"{'ret%':>9} {'DD%':>6}")
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", exit_on_stop_only=True,
                   stop_follows_safety=True, safety_line_redraw=False,
                   swing_strength=3, safety_swing_strength=12,
                   min_touches=3, max_touches=99)
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    for label, kw in MODES:
        for dist in (0.10, 0.50):
            r = run(cs, replace(base, trail_buffer_atr=dist, **kw), risk)
            s = r.stats
            if not s.get("trades"):
                print(f"  {name:<7} {label:<9} {dist:>5.2f}  -- none"); continue
            ts = r.trades
            rs = [t.r_multiple for t in ts]
            n = len(ts)
            wick = sum(1 for t in ts if t.exit_reason == "stop (wicked)") / n * 100
            hold = sum(t.exit_index - t.entry_index for t in ts) / n
            print(f"  {name:<7} {label:<9} {dist:>5.2f} {n:>5} {hold:>6.1f} "
                  f"{wick:>6.1f}% {s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
                  f"{s['avg_win_r']:>+7.2f} {min(rs):>+7.2f} {max(rs):>+7.1f} "
                  f"{s['return_pct']:>+9.1f} {s['max_drawdown_pct']:>6.1f}", flush=True)
    print(flush=True)
