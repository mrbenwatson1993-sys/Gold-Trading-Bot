"""Higher-timeframe trend alignment.

The point of the top-down read, made mechanical. If the monthly, weekly and
daily are all bullish, a 4-hour downtrend is a pullback inside a bull market,
not a trend of its own -- so breaking it upward is the larger trend resuming,
and selling the break of the ascending line would be fighting everything above
it.

Two things make this safe to use inside a backtest:

  * structure on each higher timeframe is read from swings that are already
    confirmed on that timeframe, with the usual confirmation lag;
  * a base bar only ever sees the last *completed* higher-timeframe bar. The
    weekly candle you are inside of has not printed its high or low yet, and
    using it would be reading the future.

The whole thing is precomputed once per timeframe into a per-bar array, so the
backtest pays an O(1) lookup rather than resampling the world on every bar.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from .candles import Candle, resample
from .structure import BEARISH, BULLISH, RANGING, classify
from .swings import find_swings

# Timeframes above the trading one, coarsest first.
DEFAULT_LADDER: tuple[tuple[str, int], ...] = (
    ("1M", 2_592_000), ("1w", 604_800), ("1d", 86_400),
    ("4h", 14_400), ("1h", 3_600), ("15m", 900),
)


@dataclass
class Alignment:
    """Per-bar higher-timeframe bias, ready for O(1) lookup."""

    labels: list[str]
    bias: dict[str, list[str]]     # label -> bias for every base bar

    def at(self, i: int) -> dict[str, str]:
        return {lab: self.bias[lab][i] for lab in self.labels}

    def agrees(self, i: int, direction: str, mode: str = "all") -> bool:
        """Do the higher timeframes support trading `direction` at bar `i`?

        "none"    -- no filter at all.
        "all"     -- every higher timeframe must be biased the trade's way.
        "soft"    -- none may oppose it; ranging is tolerated.
        "majority"-- more agree than oppose.
        """
        if mode == "none" or not self.labels:
            return True
        want = BULLISH if direction == "long" else BEARISH
        against = BEARISH if direction == "long" else BULLISH
        votes = [self.bias[lab][i] for lab in self.labels]
        if mode == "all":
            return all(v == want for v in votes)
        if mode == "soft":
            return not any(v == against for v in votes)
        if mode == "majority":
            return sum(v == want for v in votes) > sum(v == against for v in votes)
        raise ValueError(f"unknown alignment mode {mode!r}")


def build_alignment(candles: list[Candle], base_seconds: int,
                    labels: tuple[str, ...] = ("1d", "1w"),
                    swing_strength: int = 3,
                    min_bars: int = 30) -> Alignment:
    """Precompute each requested higher timeframe's bias for every base bar."""
    wanted = [(lab, secs) for lab, secs in DEFAULT_LADDER
              if lab in labels and secs > base_seconds]
    out: dict[str, list[str]] = {}
    kept: list[str] = []

    for label, seconds in wanted:
        htf = resample(candles, seconds)
        if len(htf) < min_bars:
            continue       # not enough history on this timeframe to read

        # Two legs, not three. "Higher high and higher low" is the textbook
        # definition of an uptrend; demanding three consecutive of each calls
        # a +41% bull market "ranging" 91% of the time, because every real
        # trend pulls back. The efficiency guard is also dropped here: it is
        # useful for deciding whether to trade a chart, but as a directional
        # vote it just converts trends into abstentions.
        swings = find_swings(htf, max(2, swing_strength - 1))
        per_htf = [classify(htf, swings, k, legs=2, min_efficiency=0.0).bias
                   for k in range(len(htf))]

        starts = [c.ts for c in htf]
        series: list[str] = []
        for c in candles:
            # index of the last HTF bar that has already CLOSED
            k = bisect_right(starts, c.ts) - 2
            series.append(per_htf[k] if k >= 0 else RANGING)
        out[label] = series
        kept.append(label)

    return Alignment(labels=kept, bias=out)
