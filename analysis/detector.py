"""Does a better trendline detector recover signal in the failed markets?

The finding so far is that on the S&P, NASDAQ, Brent and EURUSD a trendline
break predicts no better than a random bar. That was measured with one
detector: fixed-strength swing pivots threaded exactly through two anchors.
It is a weak proxy for what a person draws.

Two upgrades are tested here:
  prominence -- a pivot counts only if price retraced that far away from it
                before making a higher high, so only swings that visibly stand
                out are eligible. Fixed-strength pivots mark almost every bar.
  refit      -- the line is re-fitted by least squares through all its touches
                rather than pinned to two anchors, the way a hand-drawn line
                splits the difference.

The metric is the honest one: mean forward excursion after a break, minus the
same measurement at random bars with the same long/short mix. That subtracts
drift and leaves what the break itself contributes. If a better detector finds
signal where the crude one found none, "adds" goes positive.
"""
import random
import statistics
import sys
from dataclasses import replace

from tori.breaks import detect_break
from tori.candles import atr_series, bar_seconds, load_csv, validate
from tori.config import simple
from tori.strategy import ToriStrategy

MARKETS = [("S&P", "data/spx500_4h.csv"), ("NASDAQ", "data/nas100_4h.csv"),
           ("BRENT", "data/brent_4h.csv"), ("EURUSD", "data/eurusd_4h.csv"),
           ("GOLD", "data/gold_4h_16y.csv"), ("SILVER", "data/silver_4h.csv")]
DETECTORS = [
    ("fixed",      dict(min_prominence_atr=0.0, refit_line=False)),
    ("prom 1.5",   dict(min_prominence_atr=1.5, refit_line=False)),
    ("prom 3.0",   dict(min_prominence_atr=3.0, refit_line=False)),
    ("prom3+refit",dict(min_prominence_atr=3.0, refit_line=True)),
]
HORIZON = 30
random.seed(11)


def excursion(cs, atr, i, is_long):
    fwd = cs[i + 1:i + 1 + HORIZON]
    if len(fwd) < HORIZON or atr[i] <= 0:
        return None
    e = cs[i].close
    if is_long:
        return ((max(c.high for c in fwd) - e) - (e - min(c.low for c in fwd))) / atr[i]
    return ((e - min(c.low for c in fwd)) - (max(c.high for c in fwd) - e)) / atr[i]


print(f"  {'market':<7} {'detector':<12} {'breaks':>7} {'edge':>7} {'control':>8} "
      f"{'adds':>7} {'t':>6} {'verdict':<11}", flush=True)
for name, path in MARKETS:
    cs, _ = validate(load_csv(path))
    base = replace(simple().for_timeframe(bar_seconds(cs)), swing_strength=3,
                   min_touches=3, max_touches=99, htf_align="none",
                   prominence_window=40)
    atr = atr_series(cs, base.atr_period)
    for label, kw in DETECTORS:
        cfg = replace(base, **kw)
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
        if len(edges) < 40:
            print(f"  {name:<7} {label:<12} {len(edges):>7}  -- too few",
                  flush=True)
            continue
        # The control must be averaged over many draws. A single random sample
        # of the same size is as noisy as the signal it is compared against --
        # on an earlier run the S&P control moved from +0.439 to +0.100 purely
        # by changing the seed, which is enough to flip the conclusion.
        ctrl = []
        for _ in range(25):
            for is_long in dirs:
                j = random.randrange(warm, len(cs) - HORIZON)
                e = excursion(cs, atr, j, is_long)
                if e is not None:
                    ctrl.append(e)
        mean = statistics.fmean(edges)
        cmean = statistics.fmean(ctrl)
        adds = mean - cmean
        se = (statistics.stdev(edges) ** 2 / len(edges)
              + statistics.stdev(ctrl) ** 2 / len(ctrl)) ** 0.5
        t = adds / se if se else 0.0
        verdict = ("REAL" if t >= 2.5 else "marginal" if t >= 2.0 else "noise")
        print(f"  {name:<7} {label:<12} {len(edges):>7} {mean:>+7.3f} "
              f"{cmean:>+8.3f} {adds:>+7.3f} {t:>+6.2f} {verdict:<11}", flush=True)
    print(flush=True)
