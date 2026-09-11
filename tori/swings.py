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
