"""Is the engine actually always in the market, and how many breaks does it
see but never trade?

Always-in should mean ~100% time in a position and a flip on every break of
the line being ridden. If exposure is well under 100%, the engine is falling
flat somewhere it should not. If the book is breaking far more lines than we
take trades, we are watching signals go by.
"""
from dataclasses import replace

from tori.backtest import run
from tori.breaks import detect_break
from tori.candles import atr_series, bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple
from tori.strategy import ToriStrategy

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
cs, _ = validate(load_csv("data/gold_4h_16y.csv"))
cfg = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
              swing_strength=5, min_touches=3, htf_align="soft",
              htf_timeframes=("1d", "1w"))

r = run(cs, cfg, RISK)
ts = r.trades
bars_in = sum(t.exit_index - t.entry_index for t in ts)
span = ts[-1].exit_index - ts[0].entry_index
print(f"trades {len(ts)} over {len(cs)} bars")
print(f"  first entry bar {ts[0].entry_index}, last exit bar {ts[-1].exit_index}")
print(f"  bars held in total      {bars_in:,}")
print(f"  bars in the traded span {span:,}")
print(f"  EXPOSURE within span    {bars_in/span*100:.1f}%")
print(f"  exposure over whole file {bars_in/len(cs)*100:.1f}%")
print(f"  mean hold {bars_in/len(ts):.1f} bars ({bars_in/len(ts)*4/24:.1f} days)")

gaps = [(b.entry_index - a.exit_index) for a, b in zip(ts, ts[1:])]
flat = [g for g in gaps if g > 1]
print(f"  flat gaps >1 bar: {len(flat)}, total {sum(flat):,} bars "
      f"({sum(flat)/len(cs)*100:.1f}% of file), longest {max(flat) if flat else 0}")
print(f"  skipped for sizing: {dict(r.skipped)}")

# How much structure is the book actually carrying, and how many break events
# happen in total -- traded or not?
atr = atr_series(cs, cfg.atr_period)
strat = ToriStrategy(cs, atr, cfg)
lines_seen, breaks_seen, sampled = 0, 0, 0
warm = max(cfg.atr_period + cfg.swing_strength * 2, cfg.min_age_bars) + 5
for i in range(warm, len(cs)):
    strat._refresh_lines(i)
    lines_seen += len(strat._lines)
    sampled += 1
    for ln in strat._lines:
        if detect_break(cs, ln, i, atr[i], cfg) is not None:
            breaks_seen += 1
    strat.observe(i)
print(f"\n  mean live trendlines per bar: {lines_seen/sampled:.2f}")
print(f"  total break events in the book: {breaks_seen:,}")
print(f"  trades actually taken:          {len(ts):,}")
print(f"  breaks seen but not traded:     {breaks_seen - len(ts):,}")
