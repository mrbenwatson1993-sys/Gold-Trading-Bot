"""How sensitive is the touch count to the tolerance we allow?"""
import sys
from collections import Counter
from dataclasses import replace
from tori.candles import atr_series, bar_seconds, load_csv, timeframe_name
from tori.config import simple
from tori.strategy import ToriStrategy

for path in sys.argv[1:]:
    candles = load_csv(path)
    bs = bar_seconds(candles)
    print(f"\n{path}  {len(candles)} bars of {timeframe_name(bs)}")
    print(f"  {'tol(ATR)':>9} {'swing':>6} | " +
          "  ".join(f"{n}t" if n < 6 else "6t+" for n in range(2, 7)) +
          f"   {'lines':>7}  {'%3+':>6}")
    for swing in (2, 3):
        for tol in (0.30, 0.45, 0.75, 1.00, 1.50):
            cfg = replace(simple().for_timeframe(bs),
                          touch_tolerance_atr=tol, swing_strength=swing)
            atr = atr_series(candles, cfg.atr_period)
            strat = ToriStrategy(candles, atr, cfg)
            counts = Counter()
            warm = max(cfg.atr_period + swing * 2, cfg.min_age_bars) + 5
            # sample the book periodically rather than every bar
            for i in range(warm, len(candles), 25):
                strat._refresh_lines(i)
                for ln in strat._lines:
                    counts[min(ln.touch_count, 6)] += 1
            total = sum(counts.values())
            three_plus = sum(v for k, v in counts.items() if k >= 3)
            pct = three_plus / total * 100 if total else 0
            cells = "  ".join(f"{counts.get(n,0):>5}" for n in range(2, 7))
            print(f"  {tol:>9.2f} {swing:>6} | {cells}   {total:>7}  {pct:>5.1f}%")
