"""Strategy interface.

A strategy is a pure function from a feature frame to a list of Signals.  It
never sees the future: a signal produced on bar *i* carries ``ts`` equal to
that bar's close, and the engine only begins looking for a fill on the first
1-minute bar strictly after it.

Keeping strategies parameter-light is deliberate.  The predecessor script had
91 inputs fitted to 7 weeks of data; every free parameter is a chance to fit
noise, so each hypothesis here exposes only the knobs that carry a real
mechanical meaning.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..engine.backtest import LIMIT, MARKET, Signal


@dataclass
class RiskSpec:
    """How a signal turns into an entry, stop and target."""
    stop_atr: float = 1.0        # stop distance in ATR of the decision bar
    target_r: float = 2.0        # target as a multiple of risk
    min_stop_px: float = 0.60    # absolute floor, in dollars
    max_stop_px: float = 12.0    # absolute cap
    expiry_min: int = 20         # cancel a resting limit after this
    max_hold_h: float = 6.0      # flatten after this
    # Entry style. A resting limit at a retrace of the signal bar earns the
    # spread instead of paying it, which is worth ~0.3-0.5 of the round-trip
    # cost -- material when total costs run 0.15-0.25R. The trade-off is
    # non-fill: when price never retraces you miss the move, and the trades you
    # *do* get are selected for having stalled. Measured, not assumed.
    entry_retrace: float = 0.0   # 0 = market; >0 = limit at this fraction of the bar range


def make_signal(
    ts: int,
    side: int,
    ref_px: float,
    atr: float,
    spec: RiskSpec,
    tag: str,
    entry_type: int = MARKET,
    meta: dict | None = None,
    bar_range: float = 0.0,
) -> Signal | None:
    """Build a Signal with a cost-aware stop floor.

    The floor matters more than it looks.  A stop that is small relative to the
    spread turns a backtest into fiction: the strategy books 2R winners that a
    live account could never capture.  ``min_stop_px`` is the guard.
    """
    stop_px_dist = float(np.clip(atr * spec.stop_atr, spec.min_stop_px, spec.max_stop_px))
    if not np.isfinite(stop_px_dist) or stop_px_dist <= 0:
        return None

    entry = float(ref_px)
    if spec.entry_retrace > 0 and bar_range and np.isfinite(bar_range):
        # Rest the limit *against* the signal direction, so we are the passive
        # side of the trade rather than crossing the spread.
        entry -= bar_range * spec.entry_retrace * side
        entry_type = LIMIT

    stop = entry - stop_px_dist * side
    target = entry + stop_px_dist * spec.target_r * side
    return Signal(
        ts=int(ts),
        side=int(side),
        entry_px=entry,
        stop_px=float(stop),
        target_px=float(target),
        entry_type=entry_type,
        expiry_ms=int(spec.expiry_min * 60_000),
        max_hold_ms=int(spec.max_hold_h * 3600_000),
        tag=tag,
        meta=meta or {},
    )


def session_mask(df: pd.DataFrame, start_utc_min: int, end_utc_min: int) -> pd.Series:
    """Inclusive-start, exclusive-end mask on minutes-since-UTC-midnight."""
    if start_utc_min <= end_utc_min:
        return (df["mins_utc"] >= start_utc_min) & (df["mins_utc"] < end_utc_min)
    # wraps midnight
    return (df["mins_utc"] >= start_utc_min) | (df["mins_utc"] < end_utc_min)
