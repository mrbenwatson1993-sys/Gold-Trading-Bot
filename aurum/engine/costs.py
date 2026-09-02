"""Execution cost model.

Three separate costs, all of which the original Pine strategy modelled as
zero:

1. **Spread** - we buy the ask and sell the bid.  Taken from the *actual*
   Dukascopy quote history per minute, not a flat assumption.  Dukascopy is
   an ECN feed, so ``spread_markup`` scales it up to whatever your broker
   actually charges.
2. **Slippage** - stop-loss orders become market orders and fill worse than
   the trigger.  Limit orders never fill better than their price.
3. **Commission** - per-ounce, per-side.

The defaults are deliberately pessimistic.  A strategy that only works with
optimistic costs is not a strategy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    # Multiplier applied to the observed Dukascopy spread. Retail brokers are
    # typically 1.5-3x an ECN feed on gold.
    spread_markup: float = 2.0
    # Floor so quiet-hour quotes can't produce an unrealistically free fill.
    min_spread: float = 0.12
    # Slippage on stop-outs, in price units. Gold routinely gaps through
    # stops on news; this is a mean, not a worst case.
    stop_slippage: float = 0.05
    # Slippage on market entries.
    entry_slippage: float = 0.02
    # Commission per ounce per side (round trip = 2x).
    commission_per_side: float = 0.0

    def effective_spread(self, raw_spread: float) -> float:
        return max(raw_spread * self.spread_markup, self.min_spread)

    def round_trip_cost(self, raw_spread: float) -> float:
        """Total cost of a round trip in price units, for sizing sanity checks."""
        return (
            self.effective_spread(raw_spread)
            + self.stop_slippage
            + self.entry_slippage
            + 2.0 * self.commission_per_side
        )


# Presets so results can be reported across a cost range rather than at one
# convenient point.
TIGHT = CostModel(spread_markup=1.0, min_spread=0.08, stop_slippage=0.02,
                  entry_slippage=0.01, commission_per_side=0.0)
REALISTIC = CostModel(spread_markup=2.0, min_spread=0.12, stop_slippage=0.05,
                      entry_slippage=0.02, commission_per_side=0.0)
HARSH = CostModel(spread_markup=3.0, min_spread=0.20, stop_slippage=0.10,
                  entry_slippage=0.04, commission_per_side=0.015)
