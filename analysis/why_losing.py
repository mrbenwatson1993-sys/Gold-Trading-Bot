"""The signal is fine on indices. So what destroys it in the backtest?

break_quality.py shows the S&P break edge (+0.404 ATR) beating gold's
(+0.246) while the S&P backtest loses half the account. Something between the
signal and the P&L is doing the damage. Two candidates, both measured here:

1. Gaps. A stop cannot protect against a market that reopens past it. Indices
   gap overnight and over weekends far more than metals do, so the same stop
   rule produces bigger-than-1R losses.
2. Direction. Long edge is strong in every market measured; short edge is
   weak or negative. An always-in system is forced to take both.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import atr_series, bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("SILVER", "data/silver_4h.csv", "SIL"),
           ("S&P", "data/spx500_4h.csv", "MES"),
           ("NASDAQ", "data/nas100_4h.csv", "MNQ"),
           ("BRENT", "data/brent_4h.csv", "MCL"),
           ("EURUSD", "data/eurusd_4h.csv", "M6E"),
           ("GBPUSD", "data/gbpusd_4h.csv", "M6B"),
           ("AUDUSD", "data/audusd_4h.csv", "M6A")]

print("GAPS -- open against previous close, in ATR\n")
print(f"  {'market':<7} {'>0.5ATR':>8} {'>1ATR':>7} {'>2ATR':>7} {'worst':>7} "
      f"{'mean':>7}", flush=True)
series = {}
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    series[name] = (cs, sym)
    atr = atr_series(cs, 14)
    gaps = [abs(b.open - a.close) / atr[i] for i, (a, b)
            in enumerate(zip(cs, cs[1:])) if atr[i] > 0]
    n = len(gaps)
    big = lambda x: f"{sum(1 for g in gaps if g > x)/n*100:>6.2f}%"
    print(f"  {name:<7} {big(0.5)} {big(1.0)} {big(2.0)} "
          f"{max(gaps):>7.1f} {sum(gaps)/n:>7.3f}", flush=True)

print("\n\nDIRECTION -- both ways vs longs only vs shorts only\n")
print(f"  {'market':<7} {'side':<7} {'n':>5} {'win%':>6} {'expR':>8} {'PF':>6} "
      f"{'worst':>7} {'ret%':>9} {'DD%':>6}", flush=True)
for name, path, sym in MARKETS:
    cs, sym = series[name]
    base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", exit_on_stop_only=True,
                   stop_follows_safety=True, safety_line_redraw=False,
                   stop_on_close_only=False, stop_close_confirm_in_profit=True,
                   trail_buffer_atr=0.50, swing_strength=3,
                   safety_swing_strength=12, min_touches=3, max_touches=99)
    for side, kw in (("both", {}), ("longs", dict(allow_shorts=False)),
                     ("shorts", dict(allow_longs=False))):
        risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0, **kw)
        r = run(cs, base, risk)
        s = r.stats
        if not s.get("trades"):
            print(f"  {name:<7} {side:<7}  -- none", flush=True); continue
        worst = min(t.r_multiple for t in r.trades)
        print(f"  {name:<7} {side:<7} {s['trades']:>5} {s['win_rate']:>6.1f} "
              f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
              f"{worst:>+7.2f} {s['return_pct']:>+9.1f} "
              f"{s['max_drawdown_pct']:>6.1f}", flush=True)
    print(flush=True)
