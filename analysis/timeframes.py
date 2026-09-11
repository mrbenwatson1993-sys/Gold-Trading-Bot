"""Does the same setup work on 1H and 15m?

Two ways the settings could carry down a timeframe:

  same bars -- structure is fractal, so 60 bars of history and a swing of 12
               bars mean the same thing on any chart.
  same time -- structure lives in calendar time, so dropping from 4H to 1H
               means multiplying every bar-count by 4, and to 15m by 16.

They cannot both be right, and which one holds decides whether this is a
method you can run on any chart or one that has to be retuned per timeframe.
Everything else is the configuration that worked on 4H gold: one fixed line,
hybrid stop 0.50 ATR from it, stop-only exit, always in, 3+ touches.
"""
import sys
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name, validate
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000, risk_pct=1.0)
BASE_SECONDS = 14400          # the 4H settings are the reference

FILES = sys.argv[1:] or ["data/gold_4h_16y.csv"]
print(f"  {'tf':>4} {'scaling':<10} {'age':>5} {'sw':>3} {'safe':>5} {'n':>6} "
      f"{'hold':>6} {'days':>5} {'wick%':>7} {'expR':>8} {'PF':>6} {'worst':>7} "
      f"{'best':>7} {'ret%':>9} {'DD%':>6}", flush=True)
for path in FILES:
    cs, _ = validate(load_csv(path))
    bs = bar_seconds(cs)
    tf = timeframe_name(bs)
    ratio = max(1, round(BASE_SECONDS / bs))     # 1 on 4H, 4 on 1H, 16 on 15m
    cfg0 = replace(simple().for_timeframe(bs), always_in=True, htf_align="none",
                   exit_on_stop_only=True, stop_follows_safety=True,
                   safety_line_redraw=False, stop_on_close_only=False,
                   stop_close_confirm_in_profit=True, trail_buffer_atr=0.50,
                   min_touches=3, max_touches=99)
    variants = [("same bars", 1)] + ([("same time", ratio)] if ratio > 1 else [])
    for label, k in variants:
        cfg = replace(cfg0, min_age_bars=60 * k, swing_strength=3 * k,
                      safety_swing_strength=12 * k, min_touch_gap_bars=6 * k)
        r = run(cs, cfg, RISK)
        s = r.stats
        if not s.get("trades"):
            print(f"  {tf:>4} {label:<10}  -- no trades", flush=True); continue
        ts = r.trades
        rs = [t.r_multiple for t in ts]
        n = len(ts)
        wick = sum(1 for t in ts if t.exit_reason == "stop (wicked)") / n * 100
        hold = sum(t.exit_index - t.entry_index for t in ts) / n
        print(f"  {tf:>4} {label:<10} {cfg.min_age_bars:>5} {cfg.swing_strength:>3} "
              f"{cfg.safety_swing_strength:>5} {n:>6} {hold:>6.1f} "
              f"{hold*bs/86400:>5.1f} {wick:>6.1f}% {s['expectancy_r']:>+8.3f} "
              f"{s['profit_factor']:>6.2f} {min(rs):>+7.2f} {max(rs):>+7.1f} "
              f"{s['return_pct']:>+9.1f} {s['max_drawdown_pct']:>6.1f}", flush=True)
