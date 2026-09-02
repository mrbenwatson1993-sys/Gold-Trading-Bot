"""Look-ahead detection via synthetic data.

A strategy run on a driftless random walk has no edge to find.  Its net
expectancy must therefore come out at roughly *minus the cost drag* -- never
positive.  If any strategy shows a positive expectancy here, the feature
pipeline or the fill logic is leaking future information, and every result in
the study is worthless.

This is the cheapest possible insurance against the single most expensive
class of backtest bug.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurum.data.bars import add_features, resample
from aurum.engine.backtest import run as bt_run
from aurum.engine.costs import CostModel
from aurum.strategies import library as lib
from aurum.strategies.base import RiskSpec

ZERO = CostModel(spread_markup=0.0, min_spread=0.0,
                 stop_slippage=0.0, entry_slippage=0.0)


def synthetic_minutes(n_days: int = 220, seed: int = 11, sigma: float = 0.13,
                      start_px: float = 2000.0) -> pd.DataFrame:
    """A driftless GBM-ish 1-minute series over weekday trading hours."""
    rng = np.random.default_rng(seed)
    stamps: list[pd.Timestamp] = []
    day = pd.Timestamp("2023-01-02", tz="UTC")
    while len(stamps) < n_days * 14 * 60:
        if day.dayofweek < 5:
            base = day + pd.Timedelta(hours=6)
            stamps.extend(base + pd.Timedelta(minutes=i) for i in range(14 * 60))
        day += pd.Timedelta(days=1)

    idx = pd.DatetimeIndex(stamps)
    steps = rng.normal(0.0, sigma, len(idx))
    close = start_px + np.cumsum(steps)
    wiggle = np.abs(rng.normal(0.0, sigma * 0.6, len(idx)))
    df = pd.DataFrame(
        {
            "ts": (idx.tz_convert("UTC").tz_localize(None)
                   .astype("datetime64[ms]").astype("int64")),
            "open": close - steps,
            "high": np.maximum(close, close - steps) + wiggle,
            "low": np.minimum(close, close - steps) - wiggle,
            "close": close,
            "spread_med": np.full(len(idx), 0.30),
            "ticks": np.full(len(idx), 50),
        },
        index=idx,
    )
    return df


ALL_STRATEGIES = {
    "trend_pullback": lambda b, s: lib.trend_pullback(b, s),
    "volatility_expansion": lambda b, s: lib.volatility_expansion(b, s),
    "stretch_fade": lambda b, s: lib.stretch_fade(b, s),
    "sweep_reversal": lambda b, s: lib.sweep_reversal(b, s),
    "vwap_reversion": lambda b, s: lib.vwap_reversion(b, s),
    "reaction_zone_retest": lambda b, s: lib.reaction_zone_retest(b, s),
    "orb": lambda b, s: lib.opening_range_breakout(b, s, open_min=7 * 60),
}


@pytest.mark.parametrize("name", sorted(ALL_STRATEGIES))
def test_no_edge_on_random_walk(name):
    """Zero-cost expectancy on a random walk must be indistinguishable from 0.

    With a symmetric stop and a 2R target the R distribution is skewed, so we
    test the *mean* against zero using the trade-level standard error rather
    than demanding an exact 0.
    """
    minutes = synthetic_minutes()
    bars = add_features(resample(minutes, "15min"))
    spec = RiskSpec(stop_atr=2.0, target_r=2.0, min_stop_px=2.0,
                    max_stop_px=40.0, max_hold_h=8.0)

    sigs = ALL_STRATEGIES[name](bars, spec)
    if len(sigs) < 40:
        pytest.skip(f"{name}: too few signals on synthetic data")

    trades = bt_run(minutes, sigs, ZERO, max_concurrent=1).raw_trades
    if len(trades) < 40:
        pytest.skip(f"{name}: too few fills on synthetic data")

    r = trades["r"].to_numpy()
    t_stat = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
    assert abs(t_stat) < 3.5, (
        f"{name}: t={t_stat:+.2f} on a driftless random walk with zero costs "
        f"(E[R]={r.mean():+.4f}, n={len(r)}). Suspect look-ahead."
    )


def test_costs_always_hurt_on_random_walk():
    """With costs on, a random walk must produce a clearly negative expectancy."""
    minutes = synthetic_minutes()
    bars = add_features(resample(minutes, "15min"))
    spec = RiskSpec(stop_atr=2.0, target_r=2.0, min_stop_px=2.0, max_stop_px=40.0)
    sigs = lib.trend_pullback(bars, spec)
    costly = CostModel(spread_markup=2.0, min_spread=0.30,
                       stop_slippage=0.05, entry_slippage=0.02)
    trades = bt_run(minutes, sigs, costly, max_concurrent=1).raw_trades
    assert len(trades) > 40
    assert trades["r"].mean() < 0, "costs must reduce expectancy on a random walk"


def test_signal_timestamps_are_bar_closes_not_opens():
    """A signal must be stamped at its bar's CLOSE, so fills start after it."""
    minutes = synthetic_minutes(n_days=40)
    bars = add_features(resample(minutes, "15min"))
    spec = RiskSpec(stop_atr=2.0, target_r=2.0, min_stop_px=2.0)
    sigs = lib.trend_pullback(bars, spec)
    assert sigs, "expected some signals"
    bar_ts = set(bars["ts"].tolist())
    assert all(s.ts in bar_ts for s in sigs[:50])
