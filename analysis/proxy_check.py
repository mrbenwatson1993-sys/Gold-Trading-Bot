"""How closely does spot gold track GC futures?

Every 4-hour result in this project is measured on spot (XAUUSD or PAXG),
because deep intraday futures history is paywalled. That is only acceptable
if the two series produce the same bars. The FirstRate GC futures sample
overlaps the PAXG series, so the question is answerable rather than assumed.
"""
import os
from tori.candles import load_csv, resample, atr_series

GC = "/tmp/gcs/GC_1hour_sample.csv"
if not os.path.exists(GC):
    raise SystemExit("GC sample not present")

gc = resample(load_csv(GC), 14400)
spot = load_csv("data/gold_4h.csv")

gmap = {c.ts: c for c in gc}
pairs = [(gmap[c.ts], c) for c in spot if c.ts in gmap]
print(f"overlapping 4H bars: {len(pairs)}")
if not pairs:
    raise SystemExit("no overlap")

f, s = pairs[0]
print(f"window {pairs[0][0].dt:%Y-%m-%d} .. {pairs[-1][0].dt:%Y-%m-%d}")
print(f"  futures {f.close:.1f}   spot {s.close:.1f}   "
      f"basis {f.close - s.close:+.1f}")

# Basis (carry) is a near-constant offset and does not matter for trendlines;
# what matters is whether the *shapes* agree -- bar-to-bar returns and ranges.
import statistics
fr = [(b.close - a.close) / a.close for a, b in zip([p[0] for p in pairs],
                                                    [p[0] for p in pairs][1:])]
sr = [(b.close - a.close) / a.close for a, b in zip([p[1] for p in pairs],
                                                    [p[1] for p in pairs][1:])]
n = len(fr)
mf, ms = sum(fr)/n, sum(sr)/n
cov = sum((a-mf)*(b-ms) for a, b in zip(fr, sr)) / n
corr = cov / (statistics.pstdev(fr) * statistics.pstdev(sr))
print(f"  bar-return correlation: {corr:.4f}")

atr_f = sum(atr_series([p[0] for p in pairs], 14)) / len(pairs)
atr_s = sum(atr_series([p[1] for p in pairs], 14)) / len(pairs)
print(f"  mean ATR  futures {atr_f:.2f}   spot {atr_s:.2f}   "
      f"ratio {atr_s/atr_f:.3f}")

# The thing that actually decides trades: do the highs and lows -- the swing
# points trendlines are drawn through -- land in the same place?
dh = [abs(a.high - b.high) / atr_f for a, b in pairs]
dl = [abs(a.low - b.low) / atr_f for a, b in pairs]
print(f"  high disagreement: mean {sum(dh)/len(dh):.3f} ATR, "
      f"max {max(dh):.2f} ATR")
print(f"  low  disagreement: mean {sum(dl)/len(dl):.3f} ATR, "
      f"max {max(dl):.2f} ATR")
print(f"  (touch tolerance is 0.45 ATR; disagreement above that would move "
      f"which\n   swings count as touching a line)")

# --- timezone check --------------------------------------------------------
# A correlation near zero between spot and futures gold is not credible; the
# two are the same asset. Far more likely the export is stamped in exchange
# local time while everything else here is UTC, so the bars being compared
# are hours apart. Shift and see.
print("\n  testing timestamp offsets (exchange local time vs UTC):")
raw_gc = load_csv(GC)
best = None
for shift_h in range(-12, 13):
    shifted = [type(c)(c.ts + shift_h * 3600, c.open, c.high, c.low,
                       c.close, c.volume) for c in raw_gc]
    g = {c.ts: c for c in resample(shifted, 14400)}
    pr = [(g[c.ts], c) for c in spot if c.ts in g]
    if len(pr) < 30:
        continue
    a = [(y.close - x.close) / x.close for x, y in zip([p[0] for p in pr], [p[0] for p in pr][1:])]
    b = [(y.close - x.close) / x.close for x, y in zip([p[1] for p in pr], [p[1] for p in pr][1:])]
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    sa, sb = statistics.pstdev(a), statistics.pstdev(b)
    if sa == 0 or sb == 0:
        continue
    c_ = sum((x-ma)*(y-mb) for x, y in zip(a, b)) / len(a) / (sa*sb)
    if best is None or c_ > best[1]:
        best = (shift_h, c_, len(pr))
    if abs(c_) > 0.5:
        print(f"     shift {shift_h:+3d}h -> correlation {c_:+.4f}  (n={len(pr)})")
if best:
    print(f"  best alignment: {best[0]:+d}h, correlation {best[1]:+.4f} (n={best[2]})")
