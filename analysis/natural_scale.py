"""Can the right timescale be read off the market instead of fitted to P&L?

Sweeping the scale and keeping whatever made money is curve-fitting. But if an
instrument's own swing rhythm predicts the scale that works, the setting can
be derived from price action and the fit disappears.

Measured here, with no reference to returns at all:
  swing gap  -- median bars between consecutive confirmed swings
  leg        -- median size of a swing leg, in ATR
  eff        -- trend persistence: net move over distance travelled
  gap p99    -- how far the instrument reopens past the previous close

The P&L-optimal scale found by analysis/why_markets.py is printed beside them
so the two can be compared.
"""
import statistics
from dataclasses import replace

from tori.candles import atr_series, bar_seconds, load_csv, validate
from tori.candles import gap_profile
from tori.config import simple
from tori.swings import find_swings

MARKETS = [("GOLD", "data/gold_4h_16y.csv", 1.00), ("SILVER", "data/silver_4h.csv", 2.00),
           ("S&P", "data/spx500_4h.csv", None), ("NASDAQ", "data/nas100_4h.csv", None),
           ("BRENT", "data/brent_4h.csv", 4.00), ("EURUSD", "data/eurusd_4h.csv", None),
           ("GBPUSD", "data/gbpusd_4h.csv", None), ("USDJPY", "data/usdjpy_4h.csv", None),
           ("AUDUSD", "data/audusd_4h.csv", None)]


def efficiency(cs, step=60):
    out = []
    for a in range(0, len(cs) - step, step):
        seg = cs[a:a + step]
        travel = sum(abs(b.close - x.close) for x, b in zip(seg, seg[1:]))
        if travel > 0:
            out.append(abs(seg[-1].close - seg[0].close) / travel)
    return sum(out) / len(out) if out else 0.0


print(f"  {'market':<7} {'swing gap':>10} {'leg(ATR)':>9} {'eff':>6} "
      f"{'gap p99':>8}   {'best scale (P&L)':>17}")
for name, path, best in MARKETS:
    cs, _ = validate(load_csv(path))
    atr = atr_series(cs, 14)
    sw = find_swings(cs, 3)
    gaps = [b.index - a.index for a, b in zip(sw, sw[1:])]
    legs = [abs(b.price - a.price) / atr[b.index]
            for a, b in zip(sw, sw[1:]) if atr[b.index] > 0]
    tag = f"x{best:.2f}" if best else "none profitable"
    print(f"  {name:<7} {statistics.median(gaps):>10.1f} "
          f"{statistics.median(legs):>9.2f} {efficiency(cs):>6.3f} "
          f"{gap_profile(cs)['p99']:>8.2f}   {tag:>17}")
