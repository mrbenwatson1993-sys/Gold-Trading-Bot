"""Regime and side robustness for the daily strategy.

A trend-following result measured over a period when the underlying went up is
the most seductive kind of false positive: the strategy may simply have been
long a rising asset.  Two checks separate the mechanism from the market.

**Split by regime.** Gold was roughly flat through 2021-2023 and trended hard
from 2024. If the edge only exists in the second window, it is beta, not skill.

**Split by side.** A long-only edge in a rising market proves nothing about the
short side, and a strategy that will take shorts in production needs its short
side to have been tested. Where the trade count is lopsided, that asymmetry is
itself a finding to report rather than an inconvenience to average away.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes
from ..engine import costs as cost_presets
from ..engine.backtest import run as bt_run
from ..engine.metrics import summarise
from ..strategies import library as lib
from ..strategies.base import RiskSpec

DEFAULT_SPEC = RiskSpec(stop_atr=3.0, target_r=99.0, min_stop_px=10.0,
                        max_stop_px=200.0, trail_atr=2.0, max_hold_h=24 * 120)


def by_period(daily: pd.DataFrame, path: pd.DataFrame, periods: dict[str, tuple[str, str]],
              spec: RiskSpec = DEFAULT_SPEC, ma_len: int = 50,
              cost=cost_presets.REALISTIC) -> pd.DataFrame:
    rows = []
    for label, (a, b) in periods.items():
        sub = daily[(daily.index >= a) & (daily.index < b)]
        if len(sub) < 120:
            continue
        move = (sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100
        sigs = lib.daily_trend(sub, spec, ma_len=ma_len)
        if len(sigs) < 5:
            continue
        t = bt_run(path, sigs, cost, max_concurrent=1).trades
        if not len(t):
            continue
        s = summarise(t)
        rows.append({"period": label, "underlying_move_pct": round(move, 1),
                     "n": s["n"], "E_R": round(s["expectancy_r"], 3),
                     "total_R": round(s["total_r"], 1),
                     "win": round(s["win_rate"], 3), "t": round(s["t_stat"], 2)})
    return pd.DataFrame(rows)


def by_side(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or len(trades) == 0:
        return pd.DataFrame()
    g = trades.groupby("side")["r"]
    out = pd.DataFrame({
        "n": g.size(),
        "E_R": g.mean().round(3),
        "total_R": g.sum().round(1),
        "win": trades.groupby("side")["r"].apply(lambda s: (s > 0).mean()).round(3),
    })
    out.index = ["SHORT" if i < 0 else "LONG" for i in out.index]
    return out


def main(data_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    path = resample(minutes, "60min")
    daily = add_features(resample(minutes, "1D"))
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min().date()} -> "
          f"{minutes.index.max().date()}\n")

    periods = {
        "2021-2023 (gold flat)": ("2021-01-01", "2024-01-01"),
        "2024+ (gold bull)": ("2024-01-01", "2027-01-01"),
        "full sample": ("2021-01-01", "2027-01-01"),
    }
    reg = by_period(daily, path, periods)
    print("=== DAILY TREND BY REGIME ===")
    print(reg.to_string(index=False))
    reg.to_csv(out_dir / "regime_daily.csv", index=False)

    sigs = lib.daily_trend(daily, DEFAULT_SPEC, ma_len=50)
    trades = bt_run(path, sigs, cost_presets.REALISTIC, max_concurrent=1).trades
    sides = by_side(trades)
    print("\n=== BY SIDE (is this just being long a rising asset?) ===")
    print(sides.to_string())
    sides.to_csv(out_dir / "regime_side.csv")

    if len(sides) == 2 and sides["n"].min() < 20:
        thin = sides["n"].idxmin()
        print(f"\n  CAVEAT: only {sides['n'].min()} {thin} trades. That side of the "
              f"strategy is effectively unvalidated;\n  treat its expectancy as "
              f"unknown rather than as the number above.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out))
