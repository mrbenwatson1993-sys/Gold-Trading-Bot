"""Does a trendline break predict anything, market by market?

This ignores stops, exits and sizing entirely. It asks one question: after
price closes through a trendline, does it keep going?

For every break the next N bars are measured in ATR -- how far price runs the
break's way (MFE) against how far it runs the other way (MAE) before that.
If breaks follow through on metals and fade on indices, that is the answer and
no amount of tuning trade management will change it. If breaks follow through
everywhere, the fault is in the management, not the signal.

"edge" is mean MFE minus mean MAE: positive means the average break offers
more than it costs. "eff" is trend persistence measured without trendlines at
all -- the share of the distance price travels that it actually keeps.
"""
import sys
from dataclasses import replace

from tori.breaks import detect_break
from tori.candles import atr_series, bar_seconds, load_csv, validate
from tori.config import simple
from tori.strategy import ToriStrategy

MARKETS = [
    ("GOLD", "data/gold_4h_16y.csv"), ("SILVER", "data/silver_4h.csv"),
    ("S&P", "data/spx500_4h.csv"), ("NASDAQ", "data/nas100_4h.csv"),
    ("BRENT", "data/brent_4h.csv"), ("EURUSD", "data/eurusd_4h.csv"),
    ("GBPUSD", "data/gbpusd_4h.csv"), ("USDJPY", "data/usdjpy_4h.csv"),
    ("AUDUSD", "data/audusd_4h.csv"),
]
HORIZON = 30


def efficiency(cs, step=60):
    """Trend persistence with no trendlines involved: net move over total
    distance travelled."""
    out = []
    for a in range(0, len(cs) - step, step):
        seg = cs[a:a + step]
        travel = sum(abs(b.close - x.close) for x, b in zip(seg, seg[1:]))
        if travel > 0:
            out.append(abs(seg[-1].close - seg[0].close) / travel)
    return sum(out) / len(out) if out else 0.0


print(f"  {'market':<7} {'breaks':>7} {'eff':>6} | {'MFE':>6} {'MAE':>6} "
      f"{'edge':>7} | {'cont%':>6} | {'long':>7} {'short':>7}", flush=True)
for name, path in MARKETS:
    cs, _ = validate(load_csv(path))
    cfg = replace(simple().for_timeframe(bar_seconds(cs)), swing_strength=3,
                  min_touches=3, max_touches=99, htf_align="none")
    atr = atr_series(cs, cfg.atr_period)
    strat = ToriStrategy(cs, atr, cfg)
    mfes, maes, longs, shorts = [], [], [], []
    warm = max(cfg.atr_period + cfg.swing_strength * 2, cfg.min_age_bars) + 5
    for i in range(warm, len(cs) - HORIZON):
        strat._refresh_lines(i)
        a = atr[i]
        if a <= 0:
            continue
        for ln in list(strat._lines):
            brk = detect_break(cs, ln, i, a, cfg)
            if brk is None:
                continue
            fwd = cs[i + 1:i + 1 + HORIZON]
            entry = cs[i].close
            if brk.is_long:
                mfe = (max(c.high for c in fwd) - entry) / a
                mae = (entry - min(c.low for c in fwd)) / a
                longs.append(mfe - mae)
            else:
                mfe = (entry - min(c.low for c in fwd)) / a
                mae = (max(c.high for c in fwd) - entry) / a
                shorts.append(mfe - mae)
            mfes.append(mfe); maes.append(mae)
        strat.observe(i)
    n = len(mfes)
    if not n:
        print(f"  {name:<7}  -- no breaks", flush=True); continue
    cont = sum(1 for m, x in zip(mfes, maes) if m > x) / n * 100
    le = sum(longs) / len(longs) if longs else 0.0
    se = sum(shorts) / len(shorts) if shorts else 0.0
    print(f"  {name:<7} {n:>7} {efficiency(cs):>6.3f} | {sum(mfes)/n:>6.2f} "
          f"{sum(maes)/n:>6.2f} {(sum(mfes)-sum(maes))/n:>+7.3f} | "
          f"{cont:>5.1f}% | {le:>+7.3f} {se:>+7.3f}", flush=True)
