"""What does each parameter actually buy?

The question is whether the method has been over-engineered. The only honest
way to answer it is to strip it back to the bare idea -- a line, a close
through it, a stop on the other side -- and then add one rule at a time,
measuring what each addition is worth on the three markets the project
recommends.

Everything is measured on the same data, in R (multiples of the initial risk),
so the numbers are comparable across markets of very different volatility.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("S&P", "data/spx500_4h.csv", "MES"),
           ("GBPUSD", "data/gbpusd_4h.csv", "M6B")]

# The barest thing that can still be traded: lines off the chart's own swings,
# two touches, enter on a close through, stop on the other side of the line.
BARE = dict(always_in=True, htf_align="none", exit_on_stop_only=True,
            stop_follows_safety=True, safety_line_redraw=False,
            min_touches=2, trail_buffer_atr=0.25)

# Each rung adds exactly one rule to the one above it.
LADDER = [
    ("1. bare: one line, close through, trailing stop", {}),
    ("2. + coarse swings for the stop (12 not 3)", dict(safety_swing_strength=12)),
    ("3. + lines drawn on D/W/M, projected down", dict(line_timeframes=("1d", "1w", "1M"))),
    ("4. + 3 touches instead of 2", dict(min_touches=3)),
    ("5. + gap-calibrated minimum stop (since removed)", dict(auto_gap_stop_pct=99.0)),
    ("6. + close-confirm stop in profit [= recommended]", dict(stop_close_confirm_in_profit=True)),
]

DATA = {}
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    DATA[name] = (cs, sym)
    print(f"  loaded {name}: {len(cs)} bars", flush=True)
print()


def measure(name, overrides):
    cs, sym = DATA[name]
    base = dict(BARE)
    base.update(overrides)
    # stop_close_confirm_in_profit defaults True in the dataclass; the ladder
    # turns it on explicitly at rung 6, so it must start off.
    base.setdefault("stop_close_confirm_in_profit", False)
    cfg = replace(simple().for_timeframe(bar_seconds(cs)), **base)
    r = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=250_000.0,
                                risk_pct=1.0, compound=False))
    rs = [t.r_multiple for t in r.trades]
    if not rs:
        return 0, 0.0, 0.0, 0.0
    wins = sum(x for x in rs if x > 0)
    losses = -sum(x for x in rs if x < 0)
    pf = wins / losses if losses else float("inf")
    return len(rs), sum(rs) / len(rs), pf, sum(rs)


acc = {}
print(f"{'rule added':<50}" + "".join(f"{n:>26}" for n, _, _ in MARKETS))
print("-" * (50 + 26 * len(MARKETS)))
for label, delta in LADDER:
    acc.update(delta)
    cells = []
    for name, _, _ in MARKETS:
        n, avg, pf, tot = measure(name, acc)
        cells.append(f"{n:>5}tr {avg:+.3f}R pf{pf:>5.2f}")
    print(f"{label:<50}" + "".join(f"{c:>26}" for c in cells))
