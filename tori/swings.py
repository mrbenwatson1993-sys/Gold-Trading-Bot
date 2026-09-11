"""Swing point detection.

Everything in the strategy is built on swing highs and swing lows, so this has
to be honest about *when* a pivot becomes knowable. A pivot at bar i needs
`strength` bars to its right before it can be confirmed, so it is only visible
from bar i + strength onwards. `confirmed_at` records that, and every consumer
filters on it. Without this the backtest would quietly peek at the future.
"""

from __future__ import annotations

from dataclasses import dataclass

from .candles import Candle

HIGH = "high"
LOW = "low"


@dataclass(frozen=True)
class Swing:
    index: int          # bar index of the pivot itself
    ts: int
    price: float
    kind: str           # HIGH | LOW
    confirmed_at: int   # earliest bar index at which this pivot is knowable

    @property
    def is_high(self) -> bool:
        return self.kind == HIGH


def find_swings_prominent(candles: list[Candle], atr: list[float],
                          strength: int = 3, min_prominence_atr: float = 1.0,
                          window: int = 20) -> list[Swing]:
    """Swings a person would actually mark, rather than every N-bar pivot.

    A fixed-strength pivot counts any bar with `strength` lower bars either
    side, which in a trend is most of them. What makes a swing worth drawing a
    line through is not how many bars surround it but how far price had to
    retrace to make it -- its prominence.

    Prominence here is the smaller of the two drops away from the pivot within
    `window` bars on each side, measured in ATR. A high that price fell 2 ATR
    away from on both sides is structure; one it drifted 0.2 ATR from is not.

    Confirmation is delayed by the full window, since the right-hand side of
    the prominence cannot be known until those bars exist.
    """
    out: list[Swing] = []
    n = len(candles)
    for i in range(strength, n - strength):
        c = candles[i]
        a = atr[i] if i < len(atr) else 0.0
        if a <= 0:
            continue
        confirmed = min(n - 1, i + max(strength, window))

        is_high = (all(c.high >= b.high for b in candles[i - strength:i])
                   and all(c.high > b.high for b in candles[i + 1:i + 1 + strength]))
        is_low = (all(c.low <= b.low for b in candles[i - strength:i])
                  and all(c.low < b.low for b in candles[i + 1:i + 1 + strength]))

        if is_high:
            # Walk out each way until price exceeds this high; the deepest
            # low reached before that is the trough on that side. Prominence
            # is the shallower of the two drops -- how far price actually had
            # to give up to make this peak stand out.
            right = _trough(candles, i, +1, window, c.high, True)
            left = _trough(candles, i, -1, window, c.high, True)
            if right is not None and left is not None:
                if (c.high - max(left, right)) / a >= min_prominence_atr:
                    out.append(Swing(i, c.ts, c.high, HIGH, confirmed))

        if is_low:
            right = _trough(candles, i, +1, window, c.low, False)
            left = _trough(candles, i, -1, window, c.low, False)
            if right is not None and left is not None:
                if (min(left, right) - c.low) / a >= min_prominence_atr:
                    out.append(Swing(i, c.ts, c.low, LOW, confirmed))

    out.sort(key=lambda s: (s.index, s.kind))
    return out


def _trough(candles: list[Candle], i: int, step: int, window: int,
            level: float, for_high: bool):
    """Deepest retracement away from bar i before price passes `level` again.

    Returns None when price never exceeds the level inside the window, which
    means the pivot's prominence is not yet established either way.
    """
    extreme = None
    j = i + step
    end = i + step * window
    while (j <= end if step > 0 else j >= end) and 0 <= j < len(candles):
        c = candles[j]
        if for_high:
            if c.high > level:
                break
            extreme = c.low if extreme is None else min(extreme, c.low)
        else:
            if c.low < level:
                break
            extreme = c.high if extreme is None else max(extreme, c.high)
        j += step
    return extreme


def find_swings(candles: list[Candle], strength: int = 3) -> list[Swing]:
    """Fractal pivots: an extreme with `strength` lower bars on either side.

    Ties are resolved by requiring strict dominance on the right-hand side, so
    a flat plateau yields exactly one pivot (its last bar) rather than several.
    """
    if strength < 1:
        raise ValueError("swing strength must be >= 1")
    out: list[Swing] = []
    n = len(candles)
    for i in range(strength, n - strength):
        c = candles[i]
        left = candles[i - strength:i]
        right = candles[i + 1:i + 1 + strength]

        if (all(c.high >= b.high for b in left)
                and all(c.high > b.high for b in right)):
            out.append(Swing(i, c.ts, c.high, HIGH, i + strength))

        if (all(c.low <= b.low for b in left)
                and all(c.low < b.low for b in right)):
            out.append(Swing(i, c.ts, c.low, LOW, i + strength))

    out.sort(key=lambda s: (s.index, s.kind))
    return out


def visible_swings(swings: list[Swing], as_of: int, kind: str | None = None,
                   lookback: int | None = None) -> list[Swing]:
    """Swings a trader could actually have drawn at bar `as_of`."""
    lo = as_of - lookback if lookback else None
    return [s for s in swings
            if s.confirmed_at <= as_of
            and (kind is None or s.kind == kind)
            and (lo is None or s.index >= lo)]


def last_swing_before(swings: list[Swing], index: int, kind: str) -> Swing | None:
    """Most recent pivot of `kind` at or before `index` -- the structural
    invalidation point for a trade taken at `index`."""
    found = [s for s in swings if s.kind == kind and s.index <= index]
    return found[-1] if found else None
