"""Putting the two fixes together, across every market.

The diagnosis so far:

  * the break signal is broadly fine everywhere -- the S&P edge (+0.404 ATR)
    beats gold's (+0.246);
  * stops get leapt over on instruments that gap, which turns that signal
    negative;
  * the short side is weak or negative nearly everywhere.

Two candidate fixes. "gap" holds every stop at least the instrument's own 99th
percentile gap away from price. "htf" is the strategy's own top-down rule --
do not trade against the timeframes above -- which is the principled version
of "only take longs", since it lets shorts through when the larger trend
actually is down instead of banning them because the sample happened to rise.
"longs" is included only as the benchmark those two have to beat.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
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

VARIANTS = [
    ("base",      dict(), {}),
    ("gap",       dict(auto_gap_stop_pct=99.0), {}),
    ("gap+htf",   dict(htf_align="soft",
                       htf_timeframes=("1d", "1w")), {}),
    ("gap+longs", dict(auto_gap_stop_pct=99.0), dict(allow_shorts=False)),
]

print(f"  {'market':<7} {'variant':<9} {'n':>5} {'win%':>6} {'expR':>8} {'PF':>6} "
      f"{'worst':>7} {'ret%':>9} {'DD%':>6} {'B&H%':>8}", flush=True)
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    bh = (cs[-1].close / cs[0].close - 1) * 100
    base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", exit_on_stop_only=True,
                   stop_follows_safety=True, safety_line_redraw=False,
                   stop_on_close_only=False, stop_close_confirm_in_profit=True,
                   trail_buffer_atr=0.50, swing_strength=3,
                   safety_swing_strength=12, min_touches=3, max_touches=99)
    for label, ckw, rkw in VARIANTS:
        risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0, **rkw)
        r = run(cs, replace(base, **ckw), risk)
        s = r.stats
        if not s.get("trades"):
            print(f"  {name:<7} {label:<9}  -- none", flush=True); continue
        worst = min(t.r_multiple for t in r.trades)
        print(f"  {name:<7} {label:<9} {s['trades']:>5} {s['win_rate']:>6.1f} "
              f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
              f"{worst:>+7.2f} {s['return_pct']:>+9.1f} "
              f"{s['max_drawdown_pct']:>6.1f} {bh:>+8.1f}", flush=True)
    print(flush=True)
