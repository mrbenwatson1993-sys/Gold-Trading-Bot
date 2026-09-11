"""Market structure, and the top-down read.

Step 1 of the process is not a trade filter, it is orientation: monthly, then
weekly, then daily, then the 4-hour where the setup lives. What we need from it
mechanically is one question -- is this a trend or is this chop? -- because
"don't trade sideways markets" is one of the strategy's explicit negatives, and
trendlines forced through a range are meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass

from .candles import Candle, resample
from .swings import HIGH, LOW, Swing, find_swings, visible_swings

BULLISH = "bullish"
BEARISH = "bearish"
RANGING = "ranging"


@dataclass
class Structure:
    bias: str                 # BULLISH | BEARISH | RANGING
    highs: list[float]
    lows: list[float]
    efficiency: float         # net move / total swing travel, 0..1
    note: str = ""

    @property
    def is_trending(self) -> bool:
        return self.bias in (BULLISH, BEARISH)


def classify(candles: list[Candle], swings: list[Swing], as_of: int,
             legs: int = 3, min_efficiency: float = 0.30) -> Structure:
    """Read structure from the last few confirmed swings.

    Higher highs *and* higher lows is an uptrend; lower highs and lower lows a
    downtrend; anything else is a range. The efficiency ratio is the guard
    against a market that makes nominally higher highs while going nowhere:
    net displacement divided by the distance actually travelled between swings.
    """
    highs = [s for s in visible_swings(swings, as_of, HIGH)][-legs:]
    lows = [s for s in visible_swings(swings, as_of, LOW)][-legs:]
    hp = [s.price for s in highs]
    lp = [s.price for s in lows]
    if len(hp) < 2 or len(lp) < 2:
        return Structure(RANGING, hp, lp, 0.0, "not enough swings yet")

    rising_h = all(b > a for a, b in zip(hp, hp[1:]))
    rising_l = all(b > a for a, b in zip(lp, lp[1:]))
    falling_h = all(b < a for a, b in zip(hp, hp[1:]))
    falling_l = all(b < a for a, b in zip(lp, lp[1:]))

    ordered = sorted(highs + lows, key=lambda s: s.index)
    travel = sum(abs(b.price - a.price) for a, b in zip(ordered, ordered[1:]))
    net = abs(ordered[-1].price - ordered[0].price)
    efficiency = net / travel if travel > 0 else 0.0

    if rising_h and rising_l:
        bias, note = BULLISH, "higher highs and higher lows"
    elif falling_h and falling_l:
        bias, note = BEARISH, "lower highs and lower lows"
    else:
        bias, note = RANGING, "swings are not sequencing"

    if bias != RANGING and efficiency < min_efficiency:
        bias, note = RANGING, f"sequencing but going nowhere ({efficiency:.0%} efficient)"

    return Structure(bias, hp, lp, efficiency, note)


def top_down(candles: list[Candle], as_of: int, swing_strength: int = 3,
             periods: tuple[tuple[str, int], ...] = (
                 ("monthly", 2_592_000), ("weekly", 604_800),
                 ("daily", 86_400), ("4h", 14_400))) -> dict[str, Structure]:
    """The monthly -> weekly -> daily -> 4H read, at a point in time.

    Only bars up to `as_of` are aggregated, so this is safe to call inside a
    backtest without leaking future information.
    """
    history = candles[:as_of + 1]
    out: dict[str, Structure] = {}
    for name, seconds in periods:
        htf = resample(history, seconds)
        if len(htf) < swing_strength * 2 + 4:
            out[name] = Structure(RANGING, [], [], 0.0, "insufficient history")
            continue
        htf_swings = find_swings(htf, swing_strength)
        out[name] = classify(htf, htf_swings, len(htf) - 1)
    return out
