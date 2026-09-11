"""Does calibrating the stop to each instrument's gap risk fix the losers?

The signal measured fine on the indices -- the S&P break edge (+0.404 ATR)
beats gold's (+0.246) -- yet the S&P backtest lost half the account. The gap
profile says why: the S&P reopens more than 1 ATR past the previous close on
1.00% of bars against gold's 0.11%, with a worst gap of 11.3 ATR against 2.4.
A stop trailing close to the line is a stop on gold and a suggestion on an
index.

So: hold every stop at least as far from price as that instrument's own 99th
percentile gap, and let each market set its own number.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, gap_profile, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("SILVER", "data/silver_4h.csv", "SIL"),
           ("S&P", "data/spx500_4h.csv", "MES"),
           ("NASDAQ", "data/nas100_4h.csv", "MNQ"),
           ("BRENT", "data/brent_4h.csv", "MCL"),
           ("EURUSD", "data/eurusd_4h.csv", "M6E"),
           ("GBPUSD", "data/gbpusd_4h.csv", "M6B"),
           ("USDJPY", "data/usdjpy_4h.csv", "M6J"),
           ("AUDUSD", "data/audusd_4h.csv", "M6A")]

print(f"  {'market':<7} {'gapstop':<8} {'p99':>5} {'n':>5} {'win%':>6} {'expR':>8} "
      f"{'PF':>6} {'avgL':>6} {'worst':>7} {'ret%':>9} {'DD%':>6}", flush=True)
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    p99 = gap_profile(cs)["p99"]
    base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", exit_on_stop_only=True,
                   stop_follows_safety=True, safety_line_redraw=False,
                   stop_on_close_only=False, stop_close_confirm_in_profit=True,
                   trail_buffer_atr=0.50, swing_strength=3,
                   safety_swing_strength=12, min_touches=3, max_touches=99)
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    for label, pct in (("off", 0.0), ("p99", 99.0)):
        r = run(cs, replace(base, auto_gap_stop_pct=pct), risk)
        s = r.stats
        if not s.get("trades"):
            print(f"  {name:<7} {label:<8}  -- none", flush=True); continue
        worst = min(t.r_multiple for t in r.trades)
        print(f"  {name:<7} {label:<8} {p99:>5.2f} {s['trades']:>5} "
              f"{s['win_rate']:>6.1f} {s['expectancy_r']:>+8.3f} "
              f"{s['profit_factor']:>6.2f} {s['avg_loss_r']:>+6.2f} "
              f"{worst:>+7.2f} {s['return_pct']:>+9.1f} "
              f"{s['max_drawdown_pct']:>6.1f}", flush=True)
    print(flush=True)
