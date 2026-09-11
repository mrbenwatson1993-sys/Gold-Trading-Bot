"""Print a real trade the way the chart draws it, so the two can be compared.

The reference chart shows: three touches on a descending line, a break upward,
entry on the break, a Safety Line drawn from the breakout low up through the
higher lows that follow, and an exit when price closes back through it.

This replays the engine on real data and prints exactly those elements for
actual trades, so "is it doing what the picture shows" is answerable by
reading it rather than by trusting the summary statistics.
"""
import sys
from dataclasses import replace
from datetime import datetime, timezone

from tori.candles import atr_series, bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple
from tori.strategy import ToriStrategy

W = lambda ts: f"{datetime.fromtimestamp(ts, tz=timezone.utc):%Y-%m-%d %H:%M}"

path = sys.argv[1] if len(sys.argv) > 1 else "data/gold_4h_16y.csv"
want = int(sys.argv[2]) if len(sys.argv) > 2 else 2      # how many to print
touches = int(sys.argv[3]) if len(sys.argv) > 3 else 3   # touch count to find

cs, _ = validate(load_csv(path))
cfg = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
              htf_align="none", stop_follows_safety=True,
              stop_on_close_only=False, swing_strength=3,
              min_touches=touches, max_touches=touches)
atr = atr_series(cs, cfg.atr_period)
strat = ToriStrategy(cs, atr, cfg)

shown = 0
i = max(cfg.atr_period + cfg.swing_strength * 2, cfg.min_age_bars) + 5
while i < len(cs) - 2 and shown < want:
    sig = strat.find_signal(i)
    if sig is None:
        strat.observe(i)
        i += 1
        continue
    if not sig.is_long:          # the chart shows a long; match it
        strat.observe(i)
        i += 1
        continue

    line = sig.brk.line
    print("=" * 78)
    print(f"  {line.touch_count}-TOUCH {line.kind.upper()} LINE -> LONG")
    print("=" * 78)
    for n, t in enumerate(line.touches, 1):
        print(f"   Touch {n}      {W(t.ts)}   {t.price:>10.2f}")
    print(f"   ACTION LINE broken at {W(sig.brk.ts)}: close {sig.brk.close:.2f} "
          f"vs line {sig.brk.line_value:.2f}")
    print(f"   BUY / ENTRY  {W(cs[sig.entry_index].ts)}   {sig.entry_price:>10.2f}")
    print(f"   initial stop {sig.initial_stop:>10.2f}   (risk {sig.risk:.2f} = 1R)")

    pos = strat.open_position(sig, contracts=1)
    seen, out = None, None
    for j in range(pos.entry_index, len(cs)):
        res = strat.check_exit(pos, j)
        if pos.safety_line is not None:
            key = (pos.safety_line.anchor_index, pos.safety_line.touches[-1].index)
            if key != seen:
                seen = key
                a, b = pos.safety_line.touches[0], pos.safety_line.touches[-1]
                print(f"   SAFETY LINE  {W(a.ts)} {a.price:.2f} -> "
                      f"{W(b.ts)} {b.price:.2f}   (now at "
                      f"{pos.safety_line.value_at(j):.2f}, stop {pos.hard_stop:.2f})")
        if res is not None:
            out = (j, res)
            break
    if out:
        j, (price, reason) = out
        print(f"   EXIT         {W(cs[j].ts)}   {price:>10.2f}   [{reason}]")
        print(f"   result       {pos.r_multiple(price):+.2f}R  over "
              f"{j - pos.entry_index} bars  (peak was {pos.mfe_r:+.2f}R)")
    print()
    shown += 1
    i = (out[0] if out else i) + 1
