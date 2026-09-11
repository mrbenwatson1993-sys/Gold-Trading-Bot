"""Setup grading.

Section 10 of the method lists ten things that separate a valid setup from an
A+ one. This turns that list into a scorecard: each criterion scores 0..1, the
weighted total gives 0..100, and the letter grade follows -- with one hard
override. Fewer than three touches can never be better than a B, no matter how
good everything else looks, because the three-touch break *is* the A+ setup.

The point of scoring rather than filtering is that every trade carries its own
reasons. When a grade looks wrong you can read the line that produced it
instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .breaks import Break
from .config import StrategyConfig
from .structure import BEARISH as S_BEARISH, BULLISH as S_BULLISH, Structure
from .levels import Level, at_level


@dataclass
class Criterion:
    name: str
    weight: float
    score: float        # 0..1
    note: str

    @property
    def points(self) -> float:
        return self.weight * self.score


@dataclass
class Grade:
    score: float                 # 0..100
    letter: str                  # A+ | A | B | C | F
    criteria: list[Criterion] = field(default_factory=list)
    caps: list[str] = field(default_factory=list)

    def table(self) -> str:
        rows = [f"  {'criterion':<22} {'score':>7} {'pts':>7}   note"]
        for c in self.criteria:
            rows.append(f"  {c.name:<22} {c.score:>6.0%} "
                        f"{c.points:>6.1f}/{c.weight:<3.0f} {c.note}")
        for cap in self.caps:
            rows.append(f"  ! capped: {cap}")
        rows.append(f"  {'TOTAL':<22} {'':>7} {self.score:>6.1f}/100  -> {self.letter}")
        return "\n".join(rows)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def grade_by_touches(touches: int, cfg: StrategyConfig) -> str:
    """The grade, as the strategy actually defines it: how many times price
    respected the line before it broke.

    Three touches then a break is the A+ setup -- that is the whole claim.
    Two touches is the same shape with less evidence behind it, so it grades
    B. Everything else the engine can measure is reporting, not grading.
    """
    if touches >= cfg.a_plus_touches:
        return "A+"
    if touches == 2:
        return "B"
    return "C"


def grade_setup(brk: Break, cfg: StrategyConfig, structure: Structure,
                levels: list[Level], room_r: float, blocker: Level | None,
                stop_distance: float) -> Grade:
    line = brk.line
    atr_ref = brk.atr_ref
    crits: list[Criterion] = []

    # 1. Clear market structure -----------------------------------------
    # The trend being broken has to have been a real trend. Breaking a
    # downtrend that was never a downtrend is not a reversal.
    wanted = S_BEARISH if brk.is_long else S_BULLISH
    if structure.bias == wanted:
        s, note = 1.0, f"{structure.bias} trend to reverse ({structure.efficiency:.0%} eff)"
    elif structure.is_trending:
        s, note = 0.45, f"structure is {structure.bias}, not the trend we are breaking"
    else:
        s, note = 0.15, f"ranging -- {structure.note}"
    crits.append(Criterion("market structure", 8, s, note))

    # 2. Clean trendline ---------------------------------------------------
    tightness = _clamp(1.0 - line.rms_dev_atr / max(1e-9, cfg.touch_tolerance_atr))
    penalty = {0: 1.0, 1: 0.6}.get(line.penetrations, 0.3)
    crits.append(Criterion(
        "clean trendline", 12, tightness * penalty,
        f"touches sit {line.rms_dev_atr:.2f} ATR off the line, "
        f"{line.penetrations} ugly penetration(s)"))

    # 3. Touch count -- the defining characteristic ------------------------
    touch_score = {0: 0.0, 1: 0.0, 2: 0.45, 3: 0.85}.get(line.touch_count, 1.0)
    crits.append(Criterion("touch count", 18, touch_score,
                           f"{line.touch_count} touches"
                           + ("" if line.touch_count >= cfg.a_plus_touches
                              else f" (A+ needs {cfg.a_plus_touches})")))

    # 4. Spacing -----------------------------------------------------------
    gaps = line.touch_gaps()
    if gaps:
        ratio = min(gaps) / max(1, cfg.min_touch_gap_bars)
        s = _clamp(ratio / 2.0)
        note = f"tightest gap {min(gaps)} bars (min {cfg.min_touch_gap_bars})"
    else:
        s, note = 0.0, "no gaps to measure"
    crits.append(Criterion("touch spacing", 10, s, note))

    # 5. Age ---------------------------------------------------------------
    age = line.age_bars(brk.index)
    age_ratio = age / max(1, cfg.min_age_bars)
    days = age * cfg.bar_seconds / 86400
    crits.append(Criterion("line age", 10, _clamp(0.3 + 0.35 * age_ratio),
                           f"{age} bars / {days:.0f} days of structure"))

    # 6. Clean break -------------------------------------------------------
    disp_ratio = brk.displacement_atr / max(1e-9, cfg.break_min_displacement_atr)
    crits.append(Criterion("clean break", 12, _clamp(0.35 + 0.33 * disp_ratio),
                           f"closed {brk.displacement_atr:.2f} ATR through the line"))

    # 7. Strong directional candle (our enhancement, not a Tori rule) ------
    crits.append(Criterion("break candle", 6, _clamp((brk.body_ratio - 0.2) / 0.6),
                           f"body is {brk.body_ratio:.0%} of range"))

    # 8. Location ----------------------------------------------------------
    here = at_level(levels, brk.close, atr_ref)
    if here and here.strength >= 3.0:
        s, note = 1.0, f"breaking at a {here.touches}-touch level ({here.price:.2f})"
    elif here:
        s, note = 0.65, f"minor level nearby ({here.price:.2f})"
    else:
        s, note = 0.35, "no horizontal level at the break"
    crits.append(Criterion("location", 6, s, note))

    # 9. Clean space -------------------------------------------------------
    space_score = _clamp(room_r / max(1e-9, cfg.clean_space_min_r))
    if blocker is None:
        note = "open air to the next level"
    else:
        note = f"{room_r:.1f}R to {blocker.price:.2f} ({blocker.touches} touches)"
    crits.append(Criterion("clean space", 12, space_score, note))

    # 10. Is the Safety Line obvious? --------------------------------------
    # "If I'm wrong, where does this trade become structurally invalid?"
    # A stop that is absurdly tight or absurdly wide means the answer is not
    # actually obvious from the chart.
    stop_atr = stop_distance / atr_ref if atr_ref > 0 else 0.0
    if 0.5 <= stop_atr <= 3.0:
        s, note = 1.0, f"structural invalidation {stop_atr:.1f} ATR away"
    elif stop_atr <= 0:
        s, note = 0.0, "no structural stop available"
    else:
        s, note = 0.4, f"invalidation {stop_atr:.1f} ATR away -- awkward"
    crits.append(Criterion("safety line clear", 6, s, note))

    total = sum(c.points for c in crits)

    # --- letter ----------------------------------------------------------
    caps: list[str] = []
    if not cfg.rubric_grading:
        # Touch count alone decides the grade. The scorecard above still gets
        # computed and printed, because it is useful to read -- it just does
        # not get a vote.
        return Grade(total, grade_by_touches(line.touch_count, cfg), crits, caps)

    if total >= 85 and line.touch_count >= cfg.a_plus_touches and brk.strong:
        letter = "A+"
    elif total >= 75 and line.touch_count >= cfg.a_plus_touches:
        letter = "A"
    elif total >= 60:
        letter = "B"
    elif total >= 45:
        letter = "C"
    else:
        letter = "F"

    # The override: a two-touch break is a different, weaker setup.
    if line.touch_count < cfg.a_plus_touches and letter in ("A+", "A"):
        letter = "B"
        caps.append(f"{line.touch_count}-touch break cannot grade above B")
    if not brk.strong and letter == "A+":
        letter = "A"
        caps.append("break candle lacked displacement")

    return Grade(total, letter, crits, caps)
