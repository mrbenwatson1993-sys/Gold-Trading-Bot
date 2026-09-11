"""Are the break edges real, or is this all sampling noise?

natural_scale.py found every market has the same swing rhythm once normalised
by ATR -- same 5-bar swing gap, same 2.2-2.4 ATR legs, same efficiency. If the
price action is statistically identical, the break edge should be too, and the
differences between markets would be noise rather than a property of the
market.

So compute the standard error. edge = mean(MFE - MAE) over the 30 bars after
each break, in ATR; t = edge / SE. Anything under about 2 is not evidence.
A shuffled control is run alongside: the same measurement taken at random bars
instead of at breaks, which is what "no edge" looks like.
"""
import random
import statistics
from dataclasses import replace

from tori.breaks import detect_break
from tori.candles import atr_series, bar_seconds, load_csv, validate
from tori.config import simple
from tori.strategy import ToriStrategy

MARKETS = [("GOLD", "data/gold_4h_16y.csv"), ("SILVER", "data/silver_4h.csv"),
           ("S&P", "data/spx500_4h.csv"), ("NASDAQ", "data/nas100_4h.csv"),
           ("BRENT", "data/brent_4h.csv"), ("EURUSD", "data/eurusd_4h.csv"),
           ("GBPUSD", "data/gbpusd_4h.csv"), ("USDJPY", "data/usdjpy_4h.csv"),
           ("AUDUSD", "data/audusd_4h.csv")]
HORIZON = 30
random.seed(7)


def excursion(cs, atr, i, is_long):
    fwd = cs[i + 1:i + 1 + HORIZON]
    if len(fwd) < HORIZON or atr[i] <= 0:
        return None
    entry = cs[i].close
    if is_long:
        return ((max(c.high for c in fwd) - entry)
                - (entry - min(c.low for c in fwd))) / atr[i]
    return ((entry - min(c.low for c in fwd))
            - (max(c.high for c in fwd) - entry)) / atr[i]


print(f"  {'market':<7} {'n':>6} {'edge':>7} {'SE':>6} {'t':>6} {'verdict':<12} | "
      f"{'control':>8} {'t':>6}", flush=True)
for name, path in MARKETS:
    cs, _ = validate(load_csv(path))
    cfg = replace(simple().for_timeframe(bar_seconds(cs)), swing_strength=3,
                  min_touches=3, max_touches=99, htf_align="none")
    atr = atr_series(cs, cfg.atr_period)
    strat = ToriStrategy(cs, atr, cfg)
    edges, dirs = [], []
    warm = max(cfg.atr_period + cfg.swing_strength * 2, cfg.min_age_bars) + 5
    for i in range(warm, len(cs) - HORIZON):
        strat._refresh_lines(i)
        if atr[i] <= 0:
            continue
        for ln in list(strat._lines):
            brk = detect_break(cs, ln, i, atr[i], cfg)
            if brk is None:
                continue
            e = excursion(cs, atr, i, brk.is_long)
            if e is not None:
                edges.append(e); dirs.append(brk.is_long)
        strat.observe(i)
    if len(edges) < 30:
        print(f"  {name:<7}  -- too few breaks", flush=True); continue

    mean = statistics.fmean(edges)
    se = statistics.stdev(edges) / len(edges) ** 0.5
    t = mean / se if se else 0.0
    verdict = ("significant" if abs(t) >= 2.5 else
               "marginal" if abs(t) >= 2.0 else "noise")

    # control: same measurement at random bars, matched for direction mix
    ctrl = []
    for is_long in dirs:
        j = random.randrange(warm, len(cs) - HORIZON)
        e = excursion(cs, atr, j, is_long)
        if e is not None:
            ctrl.append(e)
    cmean = statistics.fmean(ctrl)
    cse = statistics.stdev(ctrl) / len(ctrl) ** 0.5
    print(f"  {name:<7} {len(edges):>6} {mean:>+7.3f} {se:>6.3f} {t:>+6.2f} "
          f"{verdict:<12} | {cmean:>+8.3f} {cmean/cse if cse else 0:>+6.2f}",
          flush=True)
