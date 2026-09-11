"""Tunable parameters.

Two kinds of rule live here and they are labelled as such:

  * Tori's own rules -- 3 touches, wait for the close through the line, the
    opposing trendline as the exit.
  * Mechanical refinements -- the 6-bar spacing, the 3-week age, the slope cap,
    the displacement filter. These make a discretionary method testable; they
    are our numbers, not hers, and they are meant to be tuned.

Distances are expressed in ATR multiples rather than points so the same config
works on gold, crude and the index futures.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class StrategyConfig:
    # --- swing detection -------------------------------------------------
    swing_strength: int = 3          # bars required either side of a pivot
    atr_period: int = 14

    # --- trendline construction ------------------------------------------
    touch_tolerance_atr: float = 0.45   # how near a swing must come to count
    max_close_violation_atr: float = 0.10  # a close past the line kills it
    max_penetrations: int = 1           # tolerated ugly wick pokes
    penetration_atr: float = 0.55       # a wick past this is "ugly"

    # "Don't draw a trendline wherever you can."
    min_touches: int = 2             # below this it is not a trendline at all
    a_plus_touches: int = 3          # Tori's A+ setup
    min_touch_gap_bars: int = 6      # mechanical refinement

    # Age is counted in BARS, not calendar days, and that is deliberate.
    # The same lines are drawn on the monthly and refined all the way down to
    # the 5-minute, so "3 weeks old" is meaningless on a 5m chart -- what
    # carries across timeframes is how much price action built the line.
    # Tori's worked 4H gold example runs Touch 1 -> break in 84 bars, so 60
    # keeps that trade with margin while still discarding lines conjured out
    # of a handful of candles.
    min_age_bars: int = 60
    max_slope_atr_per_bar: float = 0.75   # reject vertical lines
    min_trend_atr: float = 3.0       # the line must span a real move
    max_anchor_lookback: int = 400   # bars of history considered per scan

    # --- "wait until price reaches the line" ------------------------------
    approach_atr: float = 2.5        # only arm lines price is near

    # --- the break (Action Line) -----------------------------------------
    break_min_displacement_atr: float = 0.25  # close must clear the line
    break_min_body_ratio: float = 0.50        # displacement, not a doji poke
    entry_mode: str = "next_open"             # "next_open" | "close"

    # --- support / resistance --------------------------------------------
    level_cluster_atr: float = 0.60
    level_min_touches: int = 2
    clean_space_min_r: float = 2.0   # room to the next level, in initial-R

    # --- the Safety Line --------------------------------------------------
    safety_buffer_atr: float = 0.10  # close must clear the line to exit
    initial_stop_buffer_atr: float = 0.25
    # When the structural pivot that would define risk sits on the wrong side
    # of price, there is no swing-based stop to use. Falling flat there is
    # wrong for an always-in system -- it can leave the strategy out of the
    # market for months waiting on a fresh qualifying setup. This is the
    # fallback distance, in ATR, so the flip still happens with defined risk.
    fallback_stop_atr: float = 1.5
    safety_only_improves: bool = True  # the line ratchets, never loosens
    # Where the Safety Line is anchored, and it matters enormously.
    # "origin" fixes the first anchor at the low the new trend started from --
    # the breakout low -- and swings the far end up to each new higher low.
    # That is what Tori's own chart shows, and it keeps the line shallow so a
    # winner can breathe. "recent" re-anchors to the last two swings instead,
    # which produces a much steeper line that cuts trends short.
    safety_anchor: str = "origin"
    # There is no second trendline. There is the line price broke -- fixed,
    # never redrawn -- and a stop on the other side of it that follows price
    # as a safety net. The stop being hit IS the exit; nothing else closes a
    # trade. Setting this False restores the older two-line model where a
    # close back through an opposing line also exits.
    exit_on_stop_only: bool = True
    # A line, once drawn, does not move. The Action Line is fixed at the break
    # and only extended; with this False the Safety Line behaves the same way
    # -- drawn once from the new structure and then left alone. Redrawing it
    # to each new higher low walks it up towards price and ends the trade
    # early, which removes the long runs. What moves is the STOP, not the line.
    safety_line_redraw: bool = True
    # The Safety Line gets its own, coarser swing setting. Detecting trendline
    # touches wants sensitivity; deciding "has the trend actually broken" wants
    # the opposite. At the detection strength every three-bar dip counts as a
    # higher low, so the line ratchets up right under price and ends the trade
    # long before structure has broken -- which caps every winner near 1R and
    # removes exactly the long runs the method exists to capture.
    # 0 means "use swing_strength".
    safety_swing_strength: int = 0
    # The stop is dynamic: it rides the Safety Line, moving up every bar for a
    # long (down for a short) because the line itself slopes. It never moves
    # against the trade. Set False to step it only at confirmed swing pivots,
    # which leaves it much further from price between swings.
    stop_follows_safety: bool = True
    trail_buffer_atr: float = 0.25   # how far under the line the stop rests
    # The stop is a real resting order that fills intrabar, so a trade can
    # never lose more than the risk it was sized for. That is the whole point
    # of a fixed initial stop, and it is why this defaults to False.
    #
    # Setting it True waits for a CLOSE through the stop instead -- closer to
    # "price must actually break the line" -- but it removes the guarantee:
    # measured on 4H gold it allows single trades to lose 6.5R, because a bar
    # can drive through the level and settle far beyond it. Research only.
    stop_on_close_only: bool = False

    # --- grading ----------------------------------------------------------
    min_grade: str = "F"             # "F" = ungated: grade reports, never blocks
    # False: the grade is simply the touch count (3+ = A+, 2 = B), which is how
    # the strategy defines it. True: use the ten-criterion scorecard instead,
    # which measured no better and graded anti-predictively.
    rubric_grading: bool = False
    # Always in the market. Price under the descending line is a short; it
    # breaks up, so that exits and flips long; it breaks back through the
    # ascending line, which exits and flips short. The exit and the next entry
    # are the same event -- you are never flat, you are just trading the trend.
    always_in: bool = True
    require_trending_htf: bool = False  # block setups inside HTF chop
    # Higher-timeframe alignment: "none", "all", "soft" (nothing may oppose),
    # or "majority". With everything above bullish, a downtrend on the trading
    # timeframe is a pullback, so its break upward is the larger trend
    # resuming -- and a short there is fighting every timeframe above it.
    htf_align: str = "none"
    htf_timeframes: tuple = ("1d", "1w")
    # Research knobs: restrict which touch counts may trade at all.
    max_touches: int = 99

    # --- derived ----------------------------------------------------------
    bar_seconds: int = 14400

    @property
    def timeframe_label(self) -> str:
        from .candles import timeframe_name
        return timeframe_name(self.bar_seconds)

    @property
    def min_age_days(self) -> float:
        """The age rule expressed in calendar time, for reporting only."""
        return self.min_age_bars * self.bar_seconds / 86400.0

    def for_timeframe(self, bar_seconds: int) -> "StrategyConfig":
        return replace(self, bar_seconds=bar_seconds)


@dataclass
class RiskConfig:
    """Account and execution assumptions."""

    symbol: str = "MGC"
    starting_equity: float = 25_000.0
    risk_pct: float = 1.0            # of current equity, per trade
    max_contracts: int = 50          # hard cap regardless of sizing maths
    slippage_ticks: float = 1.0      # per fill, each way
    allow_longs: bool = True
    allow_shorts: bool = True
    compound: bool = True            # size off current equity vs starting

    def risk_dollars(self, equity: float) -> float:
        base = equity if self.compound else self.starting_equity
        return max(0.0, base * self.risk_pct / 100.0)


def simple() -> StrategyConfig:
    """The strategy as actually described: trendlines, and nothing else.

    Price decides the entry (a close through the line) and price decides the
    exit (a close back through the opposite line). Everything this project can
    additionally measure -- break displacement, candle body, horizontal levels,
    clean space, higher-timeframe structure -- is still computed and still
    reported, but none of it is allowed to block a trade.

    The only number that is not negotiable is the initial risk, because a
    futures position cannot be sized without one.
    """
    return StrategyConfig(
        min_grade="F",                  # grade is a label, not a gate
        rubric_grading=False,            # touch count is the grade
        break_min_displacement_atr=0.0,  # a close through the line is a close
        break_min_body_ratio=0.0,        # through the line
        require_trending_htf=False,
        approach_atr=999.0,              # no "is price near enough" gate
    )


GRADE_ORDER = ["F", "C", "B", "A", "A+"]


def grade_at_least(grade: str, minimum: str) -> bool:
    try:
        return GRADE_ORDER.index(grade) >= GRADE_ORDER.index(minimum)
    except ValueError:
        return False
