"""Why does this pay on metals and lose on indices and crude?

Two candidate explanations, both testable.

1. Every market was tested at gold's structural timescale. Since the settings
   proved to be anchored in time rather than bar count, a market whose swings
   run faster or slower than gold's would fail at gold's settings for reasons
   that have nothing to do with trendlines. So: sweep the scale per market and
   see whether each one has its own.

2. The break itself carries no information in those markets. That is the
   deeper possibility, and it is measured separately in break_quality.py --
   if price does not continue after a break, no amount of tuning helps.

This file is test 1.
"""
import sys
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("SILVER", "data/silver_4h.csv", "SIL"),
           ("S&P", "data/spx500_4h.csv", "MES"),
           ("NASDAQ", "data/nas100_4h.csv", "MNQ"),
           ("BRENT", "data/brent_4h.csv", "MCL")]

print(f"  {'market':<7} {'scale':>6} {'age':>5} {'sw':>3} {'safe':>5} {'n':>5} "
      f"{'hold':>6} {'days':>5} {'expR':>8} {'PF':>6} {'ret%':>9} {'DD%':>6}",
      flush=True)
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    bs = bar_seconds(cs)
    base = replace(simple().for_timeframe(bs), always_in=True, htf_align="none",
                   exit_on_stop_only=True, stop_follows_safety=True,
                   safety_line_redraw=False, stop_on_close_only=False,
                   stop_close_confirm_in_profit=True, trail_buffer_atr=0.50,
                   min_touches=3, max_touches=99)
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    best = None
    for k in (0.33, 0.5, 1.0, 2.0, 4.0):
        cfg = replace(base,
                      min_age_bars=max(10, int(60 * k)),
                      swing_strength=max(2, int(round(3 * k))),
                      safety_swing_strength=max(3, int(round(12 * k))),
                      min_touch_gap_bars=max(2, int(round(6 * k))),
                      max_anchor_lookback=max(400, int(400 * k)))
        r = run(cs, cfg, risk)
        s = r.stats
        if not s.get("trades"):
            print(f"  {name:<7} {k:>6.2f}  -- no trades", flush=True); continue
        hold = sum(t.exit_index - t.entry_index for t in r.trades) / s["trades"]
        print(f"  {name:<7} {k:>6.2f} {cfg.min_age_bars:>5} {cfg.swing_strength:>3} "
              f"{cfg.safety_swing_strength:>5} {s['trades']:>5} {hold:>6.1f} "
              f"{hold*bs/86400:>5.1f} {s['expectancy_r']:>+8.3f} "
              f"{s['profit_factor']:>6.2f} {s['return_pct']:>+9.1f} "
              f"{s['max_drawdown_pct']:>6.1f}", flush=True)
        if best is None or s["profit_factor"] > best[1]:
            best = (k, s["profit_factor"], s["return_pct"])
    if best:
        print(f"  {name:<7} best scale x{best[0]:.2f}  PF {best[1]:.2f}  "
              f"return {best[2]:+.1f}%\n", flush=True)
