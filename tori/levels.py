"""Horizontal support and resistance.

Trendlines are the trigger; horizontal levels decide whether the trigger is
worth taking. Two questions come from them:

  * Location -- did the break happen at a level that matters, or in the middle
    of nowhere?
  * Clean space -- is there room above/below the entry, or is there a wall ten
    points away?

A 3-touch break into open air and a 3-touch break into a major level are the
same signal and completely different trades.
"""

from __future__ import annotations

from dataclasses import dataclass

from .candles import Candle
from .config import StrategyConfig
from .swings import Swing, visible_swings


@dataclass
class Level:
    price: float
    touches: int
    first_index: int
    last_index: int
    strength: float     # touches, discounted by how stale the level is

    def describe(self) -> str:
        return f"{self.price:.2f} ({self.touches} touches, strength {self.strength:.1f})"


def find_levels(candles: list[Candle], swings: list[Swing], atr: list[float],
                cfg: StrategyConfig, as_of: int,
                lookback: int | None = None) -> list[Level]:
    """Cluster swing pivots into price zones.

    Highs and lows go into the same pool deliberately: broken support becomes
    resistance and vice versa, so what matters is that price has repeatedly
    turned at a price, not which way it turned.
    """
    atr_ref = atr[as_of]
    if atr_ref <= 0:
        return []
    window = lookback or cfg.max_anchor_lookback
    pivots = sorted(visible_swings(swings, as_of, None, window),
                    key=lambda s: s.price)
    if not pivots:
        return []

    tolerance = cfg.level_cluster_atr * atr_ref
    clusters: list[list[Swing]] = [[pivots[0]]]
    for s in pivots[1:]:
        if s.price - clusters[-1][-1].price <= tolerance:
            clusters[-1].append(s)
        else:
            clusters.append([s])

    levels: list[Level] = []
    for group in clusters:
        if len(group) < cfg.level_min_touches:
            continue
        last = max(s.index for s in group)
        first = min(s.index for s in group)
        # A level touched recently matters more than one from a year ago.
        staleness = (as_of - last) / max(1, window)
        levels.append(Level(
            price=sum(s.price for s in group) / len(group),
            touches=len(group), first_index=first, last_index=last,
            strength=len(group) * max(0.2, 1.0 - staleness),
        ))
    return sorted(levels, key=lambda lv: lv.price)


def nearest_level(levels: list[Level], price: float, direction: str,
                  min_distance: float = 0.0,
                  min_strength: float = 0.0) -> Level | None:
    """The first level price would run into going `direction` from `price`."""
    if direction == "long":
        ahead = [lv for lv in levels
                 if lv.price > price + min_distance and lv.strength >= min_strength]
        return min(ahead, key=lambda lv: lv.price) if ahead else None
    ahead = [lv for lv in levels
             if lv.price < price - min_distance and lv.strength >= min_strength]
    return max(ahead, key=lambda lv: lv.price) if ahead else None


def clean_space(levels: list[Level], entry: float, direction: str,
                risk: float, atr_ref: float) -> tuple[float, Level | None]:
    """Room to the next meaningful obstacle, measured in R.

    Returns (room_in_R, blocking_level). No level ahead means open air, which
    is the best case, reported as a large number rather than infinity so it
    stays comparable and printable.
    """
    if risk <= 0:
        return 0.0, None
    blocker = nearest_level(levels, entry, direction,
                            min_distance=0.25 * atr_ref, min_strength=2.0)
    if blocker is None:
        return 10.0, None
    return abs(blocker.price - entry) / risk, blocker


def at_level(levels: list[Level], price: float, atr_ref: float,
             tolerance_atr: float = 0.75) -> Level | None:
    """The level price is sitting on right now, if any -- the "good location"
    test for a break."""
    tol = tolerance_atr * atr_ref
    near = [lv for lv in levels if abs(lv.price - price) <= tol]
    return max(near, key=lambda lv: lv.strength) if near else None
