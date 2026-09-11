"""Trendlines drawn on higher timeframes and traded on a lower one.

The method is top-down: draw on the monthly, refine through the weekly and
daily, take the trade on the 4-hour. Everything before this drew lines from
the traded chart's own swings, which is a different strategy wearing the same
name -- a 4H swing is three or four hours of hesitation, not structure.

Two things make the top-down version work mechanically:

  * every Trendline stores its anchor as a timestamp and its slope per second,
    so a weekly line has a well-defined value at any 4-hour bar;
  * a higher-timeframe line only changes when a higher-timeframe bar closes,
    so the lines are built once per HTF bar and each base bar looks up the
    last CLOSED one. Using the bar currently forming would read the future.

Projection rewrites a line into the base chart's bar indices so that
everything downstream -- break detection, touch counts, ageing, grading --
keeps working without knowing which timeframe drew it.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, replace

from .candles import Candle, atr_series, resample
from .config import StrategyConfig
from .swings import Swing, find_swings, find_swings_prominent
from .trendlines import Trendline, build_trendlines

# The rules for drawing a higher-timeframe line are defined relative to
# this, so the lines do not change when the entry timeframe does.
REFERENCE_SECONDS = 14_400      # 4h

# Coarsest first; only timeframes above the traded one are used.
LADDER: tuple[tuple[str, int], ...] = (
    ("1M", 2_592_000), ("1w", 604_800), ("1d", 86_400),
    ("4h", 14_400), ("1h", 3_600), ("15m", 900),
)


def project(line: Trendline, base_ts0: int, base_seconds: int) -> Trendline:
    """Carry a line onto the base chart.

    Indices are mapped only so that touch counts and ageing read sensibly;
    the line's *price* is always taken from its timestamp and slope-per-second
    (use_ts), because bar indices and elapsed time do not correspond on a
    series with weekends in it.
    """
    def to_index(ts: int) -> int:
        return int(round((ts - base_ts0) / base_seconds))

    anchor_index = to_index(line.anchor_ts)
    slope = line.slope_per_second * base_seconds
    touches = [replace(t, index=to_index(t.ts)) for t in line.touches]
    return Trendline(
        kind=line.kind, anchor_index=anchor_index, anchor_price=line.anchor_price,
        slope=slope, touches=touches, penetrations=line.penetrations,
        rms_dev_atr=line.rms_dev_atr, net_move_atr=line.net_move_atr,
        atr_ref=line.atr_ref, anchor_ts=line.anchor_ts,
        bar_seconds=base_seconds, timeframe=line.timeframe, use_ts=True,
    )


@dataclass
class ProjectedBook:
    """Higher-timeframe lines, ready to look up by base bar."""

    labels: list[str] = field(default_factory=list)
    # label -> (htf bar start timestamps, lines as of each htf bar)
    _per_tf: dict = field(default_factory=dict)
    _index: list = field(default_factory=list)   # base bar -> list[Trendline]

    def lines_at(self, i: int) -> list[Trendline]:
        return self._index[i] if 0 <= i < len(self._index) else []


def build_projected_book(candles: list[Candle], cfg: StrategyConfig,
                         labels: tuple[str, ...] = ("1d", "1w"),
                         min_bars: int = 60) -> ProjectedBook:
    """Draw lines on each named timeframe and index them by base bar.

    Cost is one line-build per higher-timeframe bar rather than per base bar,
    which is what makes a monthly-to-4H ladder affordable: a daily series over
    sixteen years is a few thousand builds, not twenty-six thousand.
    """
    if not candles:
        return ProjectedBook()
    base_seconds = cfg.bar_seconds
    base_ts0 = candles[0].ts
    wanted = [(lab, secs) for lab, secs in LADDER
              if lab in labels and secs >= base_seconds]

    book = ProjectedBook()
    per_bar: list[list[Trendline]] = [[] for _ in candles]

    for label, seconds in wanted:
        htf = candles if seconds == base_seconds else resample(candles, seconds)
        if len(htf) < min_bars:
            continue
        # Scale the bar-count rules to keep the same amount of PRICE ACTION
        # behind a line on every rung of the ladder. Applying the traded
        # chart's numbers unchanged demands 60 monthly bars -- five years of
        # an unbroken line -- which nothing satisfies, so the monthly
        # contributed exactly zero lines before this.
        #
        # Scaled from a FIXED reference, not from the traded chart: the daily
        # line is the daily line whether you enter on the 4-hour or the
        # 5-minute. Scaling off the base would silently redraw the higher
        # timeframes every time the entry chart changed, which would make any
        # comparison between entry timeframes meaningless.
        ratio = seconds / REFERENCE_SECONDS
        tf_cfg = replace(
            cfg.for_timeframe(seconds),
            min_age_bars=max(5, round(cfg.min_age_bars / ratio)),
            min_touch_gap_bars=max(2, round(cfg.min_touch_gap_bars / ratio)),
            max_anchor_lookback=max(60, round(cfg.max_anchor_lookback / ratio)),
            prominence_window=max(5, round(cfg.prominence_window / ratio)),
        )
        atr = atr_series(htf, tf_cfg.atr_period)
        if tf_cfg.min_prominence_atr > 0:
            swings = find_swings_prominent(htf, atr, tf_cfg.swing_strength,
                                           tf_cfg.min_prominence_atr,
                                           tf_cfg.prominence_window)
        else:
            swings = find_swings(htf, tf_cfg.swing_strength)

        warm = max(tf_cfg.atr_period + tf_cfg.swing_strength * 2,
                   tf_cfg.min_age_bars) + 5
        cache: list[list[Trendline]] = [[] for _ in htf]
        for k in range(warm, len(htf)):
            if atr[k] <= 0:
                continue
            cache[k] = [project(ln, base_ts0, base_seconds) for ln in
                        build_trendlines(htf, swings, atr, tf_cfg, k)]

        starts = [c.ts for c in htf]
        for i, c in enumerate(candles):
            # the last higher-timeframe bar that has already CLOSED
            k = bisect_right(starts, c.ts) - 2
            if k >= 0 and cache[k]:
                per_bar[i].extend(cache[k])
        book.labels.append(label)

    book._index = per_bar
    return book
