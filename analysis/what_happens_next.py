"""The rules are identical everywhere. So what differs?

Every trade is the same bet: price broke the line, so it will travel further
that way than it travels back before the stop. The rule executes identically
in every market. What differs is whether the bet is right.

This takes every break, enters at the close, puts the stop 1R away, and simply
counts what happens next -- how often price reaches +1R, +2R, +3R, +5R before
it reaches -1R. No trailing, no touches, no filters. Just the bet.

If a market supplies trends, the big multiples happen and the strategy pays.
If it does not, the same rule produces the same small losses forever.
"""
from dataclasses import replace

from tori.breaks import detect_break
from tori.candles import atr_series, bar_seconds, load_csv, validate
from tori.config import simple
from tori.strategy import ToriStrategy

MARKETS = [("GOLD", "data/gold_4h_16y.csv"), ("SILVER", "data/silver_4h.csv"),
           ("S&P", "data/spx500_4h.csv"), ("NASDAQ", "data/nas100_4h.csv"),
           ("BRENT", "data/brent_4h.csv"), ("EURUSD", "data/eurusd_4h.csv"),
           ("GBPUSD", "data/gbpusd_4h.csv"), ("AUDUSD", "data/audusd_4h.csv")]
RISK_ATR = 1.5        # stop distance: 1R
MAX_BARS = 200        # give the trade room to run


def resolve(cs, i, is_long, risk):
    """Walk forward. Which comes first -- the stop, or each profit level?"""
    entry = cs[i].close
    stop = entry - risk if is_long else entry + risk
    best = 0.0
    for c in cs[i + 1:i + 1 + MAX_BARS]:
        low_r = ((c.low - entry) if is_long else (entry - c.high)) / risk
        high_r = ((c.high - entry) if is_long else (entry - c.low)) / risk
        if low_r <= -1.0:
            return max(best, 0.0) if best >= 1.0 else -1.0
        best = max(best, high_r)
    return best


print(f"  {'market':<7} {'breaks':>7} | {'stopped':>8} {'>=1R':>6} {'>=2R':>6} "
      f"{'>=3R':>6} {'>=5R':>6} | {'expectancy':>11}", flush=True)
for name, path in MARKETS:
    cs, _ = validate(load_csv(path))
    cfg = replace(simple().for_timeframe(bar_seconds(cs)), swing_strength=3,
                  min_touches=3, max_touches=99, htf_align="none")
    atr = atr_series(cs, cfg.atr_period)
    strat = ToriStrategy(cs, atr, cfg)
    outcomes = []
    warm = max(cfg.atr_period + cfg.swing_strength * 2, cfg.min_age_bars) + 5
    for i in range(warm, len(cs) - MAX_BARS):
        strat._refresh_lines(i)
        if atr[i] <= 0:
            continue
        for ln in list(strat._lines):
            brk = detect_break(cs, ln, i, atr[i], cfg)
            if brk is not None:
                outcomes.append(resolve(cs, i, brk.is_long, RISK_ATR * atr[i]))
        strat.observe(i)
    n = len(outcomes)
    if not n:
        print(f"  {name:<7}  -- no breaks", flush=True); continue
    pc = lambda x: f"{sum(1 for o in outcomes if o >= x)/n*100:>5.1f}%"
    stopped = sum(1 for o in outcomes if o <= -1.0) / n * 100
    # expectancy if you simply held for the best level reached, capped at 3R
    exp = sum(min(o, 3.0) if o > 0 else -1.0 for o in outcomes) / n
    print(f"  {name:<7} {n:>7} | {stopped:>7.1f}% {pc(1)} {pc(2)} {pc(3)} "
          f"{pc(5)} | {exp:>+10.3f}R", flush=True)
