"""Step-trailing ("ladder") exit correctness.

The ladder decides every exit price in the study that follows, so its rungs are
pinned here with hand-computable paths rather than trusted by inspection.
"""
import numpy as np
import pandas as pd
import pytest

from aurum.engine.backtest import Ladder, Signal, MARKET, resolve
from aurum.engine.costs import CostModel

ZERO = CostModel(spread_markup=0.0, min_spread=0.0,
                 stop_slippage=0.0, entry_slippage=0.0)


def path(prices):
    """1-minute frame from a close path; highs/lows equal closes for clarity."""
    p = np.asarray(prices, dtype=float)
    return pd.DataFrame({
        "ts": np.arange(len(p), dtype=np.int64) * 60_000,
        "open": p, "high": p, "low": p, "close": p,
        "spread_med": np.zeros(len(p)), "ticks": np.ones(len(p)),
    })


def sig(ladder, stop=98.0, atr=2.0):
    # entry 100, stop 98 -> risk = 2.0, so 1R = $2
    return Signal(ts=-1, side=1, entry_px=100.0, stop_px=stop, target_px=1e9,
                  entry_type=MARKET, max_hold_ms=10**9, atr=atr, ladder=ladder)


def test_breakeven_rung_prevents_a_loss():
    """Up to +1R then back through entry: the rung must save the trade."""
    m = path([100, 102, 100, 96, 96])          # +1R, then collapse
    lad = Ladder(steps=((1.0, 0.0),))          # at +1R, lock breakeven
    t, _, _ = resolve(m, [sig(lad)], ZERO)
    assert len(t) == 1
    assert t.r.iloc[0] == pytest.approx(0.0, abs=1e-9)
    assert t.reason.iloc[0] == "breakeven"


def test_without_the_rung_the_same_path_is_a_full_loss():
    m = path([100, 102, 100, 96, 96])
    t, _, _ = resolve(m, [sig(Ladder())], ZERO)
    assert t.r.iloc[0] == pytest.approx(-1.0, abs=1e-9)
    assert t.reason.iloc[0] == "stop"


def test_second_rung_locks_profit():
    """+2R arms the 0.5R lock; the pullback exits in profit, not at breakeven."""
    m = path([100, 102, 104, 100, 96])
    lad = Ladder(steps=((1.0, 0.0), (2.0, 0.5)))
    t, _, _ = resolve(m, [sig(lad)], ZERO)
    assert t.r.iloc[0] == pytest.approx(0.5, abs=1e-9)
    assert "ladder_lock" in t.reason.iloc[0]


def test_rungs_never_move_the_stop_backwards():
    """Once armed, a later smaller excursion must not loosen the stop."""
    m = path([100, 104, 101, 104, 101, 96])
    lad = Ladder(steps=((1.0, 0.0), (2.0, 0.5)))
    t, _, _ = resolve(m, [sig(lad)], ZERO)
    assert t.r.iloc[0] >= 0.5 - 1e-9


def test_give_back_fraction_keeps_a_share_of_the_peak():
    """keep 50% of best excursion: peak +4R -> stop rides at +2R."""
    m = path([100, 108, 100, 96])              # peak = +4R
    lad = Ladder(give_back_frac=0.5)
    t, _, _ = resolve(m, [sig(lad)], ZERO)
    assert t.r.iloc[0] == pytest.approx(2.0, abs=1e-9)


def test_ladder_records_max_favourable_excursion():
    m = path([100, 106, 100, 96])              # peak = +3R
    t, _, _ = resolve(m, [sig(Ladder(steps=((1.0, 0.0),)))], ZERO)
    assert t.mfe_r.iloc[0] == pytest.approx(3.0, abs=1e-6)


def test_ladder_cannot_look_ahead():
    """A rung must not fire on a level reached only AFTER the stop was hit."""
    m = path([100, 96, 110, 110])              # stopped out before the rally
    lad = Ladder(steps=((1.0, 0.0), (2.0, 1.0)))
    t, _, _ = resolve(m, [sig(lad)], ZERO)
    assert t.r.iloc[0] == pytest.approx(-1.0, abs=1e-9)
    assert t.reason.iloc[0] == "stop"


def test_fixed_target_still_honoured_alongside_ladder():
    m = path([100, 102, 104, 106])
    lad = Ladder(steps=((1.0, 0.0),), target_r=2.0)
    t, _, _ = resolve(m, [sig(lad)], ZERO)
    assert t.reason.iloc[0] == "target"
    assert t.r.iloc[0] == pytest.approx(2.0, abs=1e-9)


def test_trail_cannot_bank_a_spike_high_the_bar_closed_far_below():
    """The ratchet uses closed-bar information, never a bar's running extreme.

    Regression for a real bug. The trail was computed from each bar's high, so a
    tight give-back trail banked the top of bars it never actually held. On
    coin-flip entries at zero cost it produced +0.076 R per trade, where the
    true answer is zero.

    Here bar 1 spikes 100 -> 110 but closes at 99. A high-based trail would lock
    ~+4.5R off that spike. A close-based one sees a negative close, ratchets
    nothing, and the trade is left on its original stop.
    """
    m = pd.DataFrame({
        "ts": np.arange(3, dtype=np.int64) * 60_000,
        "open": [100.0, 100.0, 99.0],
        "high": [100.0, 110.0, 99.0],
        "low":  [100.0,  99.0, 99.0],
        "close": [100.0, 99.0, 99.0],
        "spread_med": [0.0, 0.0, 0.0], "ticks": [1, 1, 1],
    })
    lad = Ladder(give_back_frac=0.10)          # keep 90% of the peak
    t, _, _ = resolve(m, [sig(lad)], ZERO)
    assert len(t) == 1
    assert t.r.iloc[0] < 0.1, f"banked a spike it never held: {t.r.iloc[0]:+.3f}R"
    # The spike is still reported, so the excursion is visible without paying us.
    assert t.mfe_r.iloc[0] == pytest.approx(5.0, abs=1e-6)


def test_ratchet_fires_when_the_close_confirms_the_move():
    """A close that confirms the excursion does move the stop up."""
    m = pd.DataFrame({
        "ts": np.arange(3, dtype=np.int64) * 60_000,
        "open": [100.0, 100.0, 108.0],
        "high": [100.0, 110.0, 108.0],
        "low":  [100.0, 109.4, 108.0],
        "close": [100.0, 109.5, 108.0],
        "spread_med": [0.0, 0.0, 0.0], "ticks": [1, 1, 1],
    })
    # Close +9.5 -> excursion 4.75R; keeping 90% puts the stop at +4.275R,
    # which the next bar (108.0 = +4R) takes out.
    t, _, _ = resolve(m, [sig(Ladder(give_back_frac=0.10))], ZERO)
    assert t.r.iloc[0] == pytest.approx(4.275, abs=1e-6)
