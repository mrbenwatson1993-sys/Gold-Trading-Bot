"""Trendline construction and validation.

The rule that matters most here is the negative one: *don't draw a trendline
wherever you can*. Any two swing points define a line; almost none of them are
structure. A candidate survives only if

  1. it connects the right kind of pivots (lower highs / higher lows),
  2. price never closed through it while it was forming,
  3. its touches are spaced out rather than jammed together,
  4. it has existed long enough to mean something,
  5. it is not near-vertical, and
  6. it spans a move that actually happened, rather than sideways chop.

A line that needs to be nudged to make any of that true is not a line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .candles import Candle
from .config import StrategyConfig
from .swings import HIGH, LOW, Swing, visible_swings

BEARISH = "bearish"   # descending resistance, drawn across lower highs
BULLISH = "bullish"   # ascending support, drawn across higher lows


@dataclass
class Trendline:
    kind: str
    anchor_index: int         # bar index of the first touch
    anchor_price: float
    slope: float              # price per bar
    touches: list[Swing] = field(default_factory=list)
    penetrations: int = 0     # ugly wick pokes during formation
    rms_dev_atr: float = 0.0  # how tightly the touches sit on the line
    net_move_atr: float = 0.0 # size of the move the line spans
    atr_ref: float = 0.0      # ATR at build time, for scaling
    # Time coordinates. A line drawn on the weekly has to be evaluable on a
    # 5-minute chart, and bar indices do not survive that trip -- timestamps
    # do. Every line therefore carries where it was drawn and how wide its
    # bars were, so it can be projected onto any other timeframe.
    anchor_ts: int = 0
    bar_seconds: int = 0
    timeframe: str = ""

    # --- geometry ---------------------------------------------------------
    def value_at(self, index: int) -> float:
        return self.anchor_price + self.slope * (index - self.anchor_index)

    @property
    def slope_per_second(self) -> float:
        return self.slope / self.bar_seconds if self.bar_seconds else 0.0

    def value_at_ts(self, ts: int) -> float:
        """The line's price at a wall-clock time, on any timeframe."""
        return self.anchor_price + self.slope_per_second * (ts - self.anchor_ts)

    @property
    def is_bearish(self) -> bool:
        return self.kind == BEARISH

    @property
    def break_direction(self) -> str:
        """A bearish line broken upward is a long; a bullish line broken
        downward is a short."""
        return "long" if self.is_bearish else "short"

    @property
    def touch_count(self) -> int:
        return len(self.touches)

    @property
    def first_index(self) -> int:
        return self.touches[0].index if self.touches else self.anchor_index

    @property
    def last_touch_index(self) -> int:
        return self.touches[-1].index if self.touches else self.anchor_index

    @property
    def span_bars(self) -> int:
        return self.last_touch_index - self.first_index

    def age_bars(self, as_of: int) -> int:
        return as_of - self.first_index

    def touch_gaps(self) -> list[int]:
        return [b.index - a.index for a, b in zip(self.touches, self.touches[1:])]

    def slope_atr(self) -> float:
        return abs(self.slope) / self.atr_ref if self.atr_ref > 0 else 0.0

    def key(self) -> tuple:
        """Identity for de-duplication across rebuilds."""
        return (self.kind, self.first_index, self.last_touch_index,
                round(self.slope, 6))

    def describe(self, as_of: int) -> str:
        arrow = "\\" if self.slope < 0 else "/"
        return (f"{self.kind:<7} {arrow} {self.touch_count} touches, "
                f"{self.age_bars(as_of)} bars old, "
                f"line @ {self.value_at(as_of):.2f}")


def build_trendlines(candles: list[Candle], swings: list[Swing],
                     atr: list[float], cfg: StrategyConfig, as_of: int,
                     intact_through: int | None = None) -> list[Trendline]:
    """Every trendline a trader could legitimately have drawn by bar `as_of`.

    `intact_through` is the last bar the line must survive unbroken. When
    hunting for a break at bar `as_of` you pass `as_of - 1`, so that the
    breaking candle itself does not disqualify the line it is breaking.
    """
    if as_of >= len(candles) or as_of < 0:
        return []
    through = as_of if intact_through is None else intact_through
    atr_ref = atr[as_of]
    if atr_ref <= 0:
        return []

    lines: list[Trendline] = []
    for kind, pivot in ((BEARISH, HIGH), (BULLISH, LOW)):
        pool = visible_swings(swings, as_of, pivot, cfg.max_anchor_lookback)
        for i, a in enumerate(pool):
            for b in pool[i + 1:]:
                line = _try_line(candles, pool, atr, cfg, kind, a, b,
                                 as_of, through, atr_ref)
                if line is not None:
                    lines.append(line)
    return _dedupe(lines, as_of, cfg, atr_ref)


def _try_line(candles, pool, atr, cfg, kind, a: Swing, b: Swing,
              as_of: int, through: int, atr_ref: float) -> Trendline | None:
    span = b.index - a.index
    if span < cfg.min_touch_gap_bars:
        return None

    slope = (b.price - a.price) / span
    # Lower highs slope down; higher lows slope up. Anything else is not a
    # trend in that direction, however neatly the two points line up.
    if kind == BEARISH and slope >= 0:
        return None
    if kind == BULLISH and slope <= 0:
        return None
    if abs(slope) > cfg.max_slope_atr_per_bar * atr_ref:
        return None   # near-vertical: a spike, not structure

    line = Trendline(kind=kind, anchor_index=a.index, anchor_price=a.price,
                     slope=slope, atr_ref=atr_ref,
                     anchor_ts=candles[a.index].ts, bar_seconds=cfg.bar_seconds,
                     timeframe=cfg.timeframe_label)

    tol = cfg.touch_tolerance_atr * atr_ref
    close_tol = cfg.max_close_violation_atr * atr_ref
    pen_tol = cfg.penetration_atr * atr_ref

    # --- touches: pivots that came to the line and respected it ----------
    raw: list[Swing] = []
    for s in pool:
        if s.index < a.index or s.index > as_of:
            continue
        if abs(s.price - line.value_at(s.index)) <= tol:
            raw.append(s)
    touches = _space_out(raw, cfg.min_touch_gap_bars)
    if len(touches) < cfg.min_touches:
        return None
    if a not in touches or b not in touches:
        return None   # the anchors must themselves be clean touches

    line.touches = touches
    last_touch = touches[-1].index

    # --- the line must not have been broken while it was forming ---------
    # Closes are checked all the way to `through`; wicks only while forming,
    # because a wick beyond the line after the last touch is the market
    # testing it, not disrespecting it.
    penetrations = 0
    for j in range(a.index, through + 1):
        c = candles[j]
        level = line.value_at(j)
        if kind == BEARISH:
            if c.close > level + close_tol:
                return None
            if j <= last_touch and c.high > level + pen_tol:
                penetrations += 1
        else:
            if c.close < level - close_tol:
                return None
            if j <= last_touch and c.low < level - pen_tol:
                penetrations += 1
    if penetrations > cfg.max_penetrations:
        return None   # "minimal ugly penetrations"
    line.penetrations = penetrations

    # --- age: a line built this week carries little information ----------
    if line.age_bars(as_of) < cfg.min_age_bars:
        return None

    # --- the line must span a move, not chop -----------------------------
    net_move = abs(line.value_at(last_touch) - line.value_at(touches[0].index))
    line.net_move_atr = net_move / atr_ref
    if line.net_move_atr < cfg.min_trend_atr:
        return None

    devs = [abs(s.price - line.value_at(s.index)) for s in touches]
    line.rms_dev_atr = (sum(d * d for d in devs) / len(devs)) ** 0.5 / atr_ref
    return line


def _space_out(swings: list[Swing], min_gap: int) -> list[Swing]:
    """Keep touches that are genuinely separated in time.

    Three pivots inside a single consolidation are one touch, not three, so
    greedily drop any pivot that falls within `min_gap` bars of the last one
    kept. This is what stops a cluster of noise from manufacturing an A+ grade.
    """
    kept: list[Swing] = []
    for s in swings:
        if not kept or s.index - kept[-1].index >= min_gap:
            kept.append(s)
    return kept


def _dedupe(lines: list[Trendline], as_of: int, cfg: StrategyConfig,
            atr_ref: float) -> list[Trendline]:
    """Collapse near-identical lines, keeping the best-evidenced one.

    Many anchor pairs describe the same piece of structure. Two lines are the
    same line if they sit within half a touch-tolerance of each other at the
    current bar and run at a similar angle.
    """
    tol = 0.5 * cfg.touch_tolerance_atr * atr_ref
    slope_tol = 0.15 * atr_ref

    def rank(t: Trendline) -> tuple:
        return (t.touch_count, t.age_bars(as_of), -t.penetrations, -t.rms_dev_atr)

    kept: list[Trendline] = []
    for line in sorted(lines, key=rank, reverse=True):
        here = line.value_at(as_of)
        if any(line.kind == k.kind
               and abs(here - k.value_at(as_of)) <= tol
               and abs(line.slope - k.slope) <= slope_tol
               for k in kept):
            continue
        kept.append(line)
    return kept


def near_price(line: Trendline, candle: Candle, index: int,
               atr_ref: float, cfg: StrategyConfig) -> bool:
    """STEP 4 -- do nothing until price actually reaches the line."""
    distance = abs(candle.close - line.value_at(index))
    return distance <= cfg.approach_atr * atr_ref
