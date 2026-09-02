"""Engine correctness tests. These guard the numbers the whole study rests on."""
import numpy as np, pandas as pd, pytest
from aurum.engine.backtest import Signal, resolve, apply_caps, MARKET, LIMIT
from aurum.engine.costs import CostModel


def _minutes(prices, spread=0.20, start=0):
    n = len(prices)
    return pd.DataFrame({
        "ts": np.arange(n, dtype=np.int64) * 60_000 + start,
        "open": prices, "high": prices, "low": prices, "close": prices,
        "spread_med": np.full(n, spread), "ticks": np.ones(n),
    })


C0 = CostModel(spread_markup=0.0, min_spread=0.0, stop_slippage=0.0, entry_slippage=0.0)


def test_long_target_gives_exactly_target_r():
    px = np.array([100.0] + [100.0] * 5 + [104.0] * 5)
    m = _minutes(px)
    s = Signal(ts=0, side=1, entry_px=100.0, stop_px=98.0, target_px=104.0,
               entry_type=MARKET, max_hold_ms=10**9)
    t, amb, exp = resolve(m, [s], C0)
    assert len(t) == 1
    assert t.reason.iloc[0] == "target"
    assert t.r.iloc[0] == pytest.approx(2.0, abs=1e-9)


def test_long_stop_gives_minus_one_r():
    px = np.array([100.0] * 3 + [98.0] * 5)
    m = _minutes(px)
    s = Signal(ts=0, side=1, entry_px=100.0, stop_px=98.0, target_px=104.0,
               entry_type=MARKET, max_hold_ms=10**9)
    t, _, _ = resolve(m, [s], C0)
    assert t.reason.iloc[0] == "stop"
    assert t.r.iloc[0] == pytest.approx(-1.0, abs=1e-9)


def test_spread_is_actually_charged():
    """A long must buy the ask, so a flat market loses the spread."""
    px = np.full(20, 100.0)
    m = _minutes(px, spread=0.50)
    cost = CostModel(spread_markup=1.0, min_spread=0.0,
                     stop_slippage=0.0, entry_slippage=0.0)
    s = Signal(ts=0, side=1, entry_px=100.0, stop_px=95.0, target_px=110.0,
               entry_type=MARKET, max_hold_ms=5 * 60_000)
    t, _, _ = resolve(m, [s], cost)
    # Buy the ask at 100.25, sell the bid at 99.75: -0.50 in price terms.
    # Risk is measured from the *filled* price, so the denominator is
    # 100.25 - 95.00 = 5.25, not the nominal 5.00.
    assert t.entry_px.iloc[0] == pytest.approx(100.25)
    assert t.risk_px.iloc[0] == pytest.approx(5.25)
    assert t.r.iloc[0] == pytest.approx(-0.50 / 5.25, abs=1e-6)


def test_ambiguous_bar_resolves_as_a_loss():
    """When one minute contains both stop and target we must assume the stop."""
    m = pd.DataFrame({
        "ts": np.array([0, 60_000], dtype=np.int64),
        "open": [100.0, 100.0], "high": [100.0, 105.0], "low": [100.0, 97.0],
        "close": [100.0, 100.0], "spread_med": [0.0, 0.0], "ticks": [1, 1],
    })
    s = Signal(ts=-1, side=1, entry_px=100.0, stop_px=98.0, target_px=104.0,
               entry_type=MARKET, max_hold_ms=10**9)
    t, amb, _ = resolve(m, [s], C0)
    assert amb == 1
    assert t.reason.iloc[0] == "stop_ambiguous"
    assert t.r.iloc[0] < 0


def test_limit_entry_expires_when_never_touched():
    px = np.full(30, 100.0)
    m = _minutes(px)
    s = Signal(ts=0, side=1, entry_px=95.0, stop_px=93.0, target_px=99.0,
               entry_type=LIMIT, expiry_ms=5 * 60_000)
    t, _, expired = resolve(m, [s], C0)
    assert len(t) == 0 and expired == 1


def test_concurrency_cap_blocks_overlap():
    trades = pd.DataFrame({
        "entry_ts": [0, 60_000, 10_000_000],
        "exit_ts": [5_000_000, 6_000_000, 11_000_000],
        "r": [1.0, 1.0, 1.0],
        "entry_dt": pd.to_datetime([0, 60_000, 10_000_000], unit="ms", utc=True),
    })
    assert len(apply_caps(trades, max_concurrent=1)) == 2
    assert len(apply_caps(trades, max_concurrent=2)) == 3


def test_daily_loss_breaker_stops_further_trades():
    ts = pd.to_datetime([0, 3_600_000, 7_200_000], unit="ms", utc=True)
    trades = pd.DataFrame({
        "entry_ts": [0, 3_600_000, 7_200_000],
        "exit_ts": [100, 3_600_100, 7_200_100],
        "r": [-2.0, -2.0, 5.0],
        "entry_dt": ts,
    })
    kept = apply_caps(trades, max_concurrent=5, max_daily_loss_r=3.0)
    assert len(kept) == 2  # third is blocked: day is already -4R


def test_daily_trend_confirmation_bars_actually_produce_signals():
    """confirm_bars > 1 must still fire, on the bar completing the run.

    The first implementation tested "the last N bars are all on one side" on the
    crossing bar itself -- which is never true, because a crossing bar differs
    from its predecessor by definition. It silently produced zero signals for
    every confirm_bars > 1.
    """
    import numpy as np
    import pandas as pd
    from aurum.data.bars import add_features
    from aurum.strategies import library as lib
    from aurum.strategies.base import RiskSpec

    # A clean V: 120 bars down, then 120 up. Any sane rule crosses twice.
    n = 240
    px = np.concatenate([np.linspace(2000, 1800, n // 2),
                         np.linspace(1800, 2100, n // 2)])
    idx = pd.date_range("2022-01-03", periods=n, freq="D", tz="UTC")
    df = pd.DataFrame(
        {
            "ts": idx.tz_convert("UTC").tz_localize(None)
                     .astype("datetime64[ms]").astype("int64"),
            "open": px, "high": px + 4, "low": px - 4, "close": px,
            "spread_med": np.full(n, 0.3), "ticks": np.full(n, 100),
        },
        index=idx,
    )
    bars = add_features(df)
    spec = RiskSpec(stop_atr=3.0, target_r=99.0, min_stop_px=10.0,
                    max_stop_px=200.0, trail_atr=2.0)

    counts = {c: len(lib.daily_trend(bars, spec, ma_len=20, confirm_bars=c))
              for c in (1, 2, 3)}
    for c, k in counts.items():
        assert k > 0, f"confirm_bars={c} produced no signals at all: {counts}"
