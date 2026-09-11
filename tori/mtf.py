"""Multi-timeframe trendlines and the apex.

The lines are not redrawn per timeframe -- they are the *same* lines, drawn on
the monthly and carried down, nudged as finer bars reveal exactly where the
swings sat. Because every Trendline stores its anchor as a timestamp and its
slope per second, a weekly line can be evaluated on a 5-minute chart without
any conversion, and lines from every timeframe live in one price/time space.

What that overlay shows is the structure this strategy is really hunting: a
descending line coming down from above and an ascending line coming up from
below, both extended, converging on a point with price compressed inside. A
triangle with price in it, waiting to break one way or the other. When it
breaks, the line it broke becomes the Action Line and the other one -- already
drawn, already extended -- is the Safety Line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .candles import Candle, atr_series, resample, timeframe_name
from .config import StrategyConfig
from .structure import Structure, classify
from .swings import find_swings
from .trendlines import BEARISH, BULLISH, Trendline, build_trendlines

# Monthly -> weekly -> daily -> 4h -> 1h -> 15m -> 5m. The ladder is walked
# top down, exactly the way the analysis is done.
LADDER: tuple[tuple[str, int], ...] = (
    ("1M", 2_592_000), ("1w", 604_800), ("1d", 86_400),
    ("4h", 14_400), ("1h", 3_600), ("15m", 900), ("5m", 300),
)


@dataclass
class TimeframeView:
    label: str
    seconds: int
    bars: int
    lines: list[Trendline] = field(default_factory=list)
    structure: Structure | None = None

    def summary(self, ts: int) -> str:
        bias = self.structure.bias if self.structure else "?"
        return (f"{self.label:>3} ({self.bars:>4} bars, {bias:<7}) "
                f"{len(self.lines)} live line(s)")


@dataclass
class Apex:
    """Two converging, extended trendlines with price between them."""
    upper: Trendline          # descending resistance
    lower: Trendline          # ascending support
    ts: int
    upper_price: float
    lower_price: float
    close: float
    atr_ref: float
    apex_ts: int | None = None

    @property
    def gap(self) -> float:
        return self.upper_price - self.lower_price

    @property
    def gap_atr(self) -> float:
        return self.gap / self.atr_ref if self.atr_ref > 0 else 0.0

    @property
    def price_inside(self) -> bool:
        return self.lower_price <= self.close <= self.upper_price

    @property
    def position_in_range(self) -> float:
        """0.0 sitting on support, 1.0 sitting on resistance."""
        return (self.close - self.lower_price) / self.gap if self.gap > 0 else 0.5

    def seconds_to_apex(self) -> float | None:
        if self.apex_ts is None:
            return None
        return self.apex_ts - self.ts

    def bars_to_apex(self, bar_seconds: int) -> float | None:
        secs = self.seconds_to_apex()
        return secs / bar_seconds if secs is not None and bar_seconds else None

    @property
    def touches(self) -> int:
        return self.upper.touch_count + self.lower.touch_count

    def describe(self, bar_seconds: int = 0) -> str:
        bars = self.bars_to_apex(bar_seconds)
        when = f", apex in ~{bars:.0f} bars" if bars is not None else ""
        where = (f"price {self.position_in_range:.0%} of the way up"
                 if self.price_inside else "price outside")
        return (f"{self.upper.timeframe}/{self.lower.timeframe} triangle: "
                f"{self.lower_price:.2f} - {self.upper_price:.2f} "
                f"({self.gap_atr:.1f} ATR wide, "
                f"{self.upper.touch_count}+{self.lower.touch_count} touches){when}; {where}")


def build_ladder(candles: list[Candle], cfg: StrategyConfig, as_of: int,
                 ladder: tuple[tuple[str, int], ...] = LADDER,
                 min_bars: int = 60) -> list[TimeframeView]:
    """Draw the lines on every timeframe from the monthly down to the base.

    Only history up to `as_of` is used, so this is safe inside a backtest.
    Timeframes finer than the source data are skipped -- 5-minute lines cannot
    be conjured from 4-hour candles.
    """
    history = candles[:as_of + 1]
    if not history:
        return []
    base = cfg.bar_seconds

    views: list[TimeframeView] = []
    for label, seconds in ladder:
        if seconds < base:
            continue          # finer than the data we have
        htf = history if seconds == base else resample(history, seconds)
        if len(htf) < min_bars:
            continue          # not enough bars to mean anything
        tf_cfg = cfg.for_timeframe(seconds)
        swings = find_swings(htf, tf_cfg.swing_strength)
        atr = atr_series(htf, tf_cfg.atr_period)
        last = len(htf) - 1
        views.append(TimeframeView(
            label=label, seconds=seconds, bars=len(htf),
            lines=build_trendlines(htf, swings, atr, tf_cfg, last),
            structure=classify(htf, swings, last),
        ))
    return views


def all_lines(views: list[TimeframeView]) -> list[Trendline]:
    return [ln for v in views for ln in v.lines]


def find_apexes(views: list[TimeframeView], candle: Candle, atr_ref: float,
                cfg: StrategyConfig, max_gap_atr: float = 6.0,
                require_inside: bool = True) -> list[Apex]:
    """Every converging pair of extended lines, across all timeframes.

    Pairs may straddle timeframes -- a weekly descending line over a 4-hour
    ascending one is the common case, and is exactly the structure that shows
    up as a triangle when you walk the analysis down.
    """
    lines = all_lines(views)
    uppers = [ln for ln in lines if ln.kind == BEARISH]
    lowers = [ln for ln in lines if ln.kind == BULLISH]
    ts = candle.ts

    out: list[Apex] = []
    for up in uppers:
        u_now, u_slope = up.value_at_ts(ts), up.slope_per_second
        for lo in lowers:
            l_now, l_slope = lo.value_at_ts(ts), lo.slope_per_second
            gap = u_now - l_now
            if gap <= 0:
                continue                      # already crossed over
            if atr_ref > 0 and gap / atr_ref > max_gap_atr:
                continue                      # too wide to be a coil
            closing = u_slope - l_slope
            if closing >= 0:
                continue                      # diverging, never meets
            apex = Apex(upper=up, lower=lo, ts=ts, upper_price=u_now,
                        lower_price=l_now, close=candle.close, atr_ref=atr_ref,
                        apex_ts=int(ts - gap / closing))
            if require_inside and not apex.price_inside:
                continue
            out.append(apex)

    # Tightest and best-evidenced first: that is the one about to resolve.
    out.sort(key=lambda a: (a.gap_atr, -a.touches))
    return out


def confluence(views: list[TimeframeView], ts: int, price: float,
               atr_ref: float, tolerance_atr: float = 0.75) -> list[Trendline]:
    """Lines from different timeframes sitting on top of each other.

    Several timeframes agreeing on one line is the same argument as several
    touches on one timeframe: more structure stands behind it, so breaking it
    means more.
    """
    tol = tolerance_atr * atr_ref
    return sorted((ln for ln in all_lines(views)
                   if abs(ln.value_at_ts(ts) - price) <= tol),
                  key=lambda ln: -ln.touch_count)
