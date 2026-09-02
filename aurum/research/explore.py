"""Measure the market before trying to trade it.

Everything here is descriptive, not a strategy.  The point is to answer four
questions with data rather than assumption:

1. When is gold actually tradeable?  (movement relative to spread)
2. Does gold trend or mean-revert intraday, and at what horizon?
3. Is there any directional structure by hour or weekday?
4. What does the cost floor imply about the minimum sensible stop?

Answering these first is what stops you designing a strategy for hours that
cannot pay for themselves.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes


def liquidity_map(minutes: pd.DataFrame) -> pd.DataFrame:
    """Movement-to-cost by UTC hour.

    ``edge_ratio`` is the headline: average 5-minute true range divided by the
    round-trip spread cost.  Below ~2 there is not enough movement in the bar
    to pay for entering and exiting it.
    """
    m = minutes.copy()
    m["hour"] = m.index.hour
    five = resample(m, "5min")
    five["hour"] = five.index.hour
    five["rng"] = five["high"] - five["low"]

    g = five.groupby("hour")
    out = pd.DataFrame(
        {
            "median_spread": g["spread_med"].median(),
            "p90_spread": g["spread_med"].quantile(0.90),
            "mean_5m_range": g["rng"].mean(),
            "median_5m_range": g["rng"].median(),
            "mean_ticks": g["ticks"].mean(),
        }
    )
    out["edge_ratio"] = out["mean_5m_range"] / out["median_spread"]
    out["abs_ret_bps"] = (
        five.assign(r=(five["close"] / five["open"] - 1).abs() * 1e4)
        .groupby("hour")["r"]
        .mean()
    )
    return out.round(3)


def autocorrelation_profile(minutes: pd.DataFrame, rules=("5min", "15min", "30min", "60min")) -> pd.DataFrame:
    """Does gold trend or revert, and over what horizon?

    Positive lag-1 autocorrelation of returns => momentum (breakouts pay).
    Negative => mean reversion (fades pay).  Near zero => neither, and any
    apparent edge is coming from somewhere else.

    Also reports the variance ratio: VR > 1 means trending, VR < 1 reverting.
    """
    rows = []
    for rule in rules:
        b = resample(minutes, rule)
        r = np.log(b["close"] / b["close"].shift(1)).dropna()
        if len(r) < 200:
            continue
        ac = [r.autocorr(lag=k) for k in (1, 2, 3, 5, 10)]
        # Lo-MacKinlay style variance ratio at q=4.
        q = 4
        var1 = r.var()
        varq = r.rolling(q).sum().dropna().var() / q
        rows.append(
            {
                "tf": rule,
                "n": len(r),
                "ac1": ac[0], "ac2": ac[1], "ac3": ac[2],
                "ac5": ac[3], "ac10": ac[4],
                "var_ratio_q4": varq / var1 if var1 > 0 else np.nan,
                "ann_vol_pct": r.std() * np.sqrt(252 * 24 * 60 / _minutes_of(rule)) * 100,
            }
        )
    return pd.DataFrame(rows).round(4)


def _minutes_of(rule: str) -> int:
    return int(pd.Timedelta(rule).total_seconds() // 60)


def hour_of_day_drift(bars: pd.DataFrame) -> pd.DataFrame:
    """Mean return and hit rate by UTC hour, with a t-stat.

    This is where most 'session bias' claims die.  With ~24 hours tested, a
    |t| of 2 somewhere is expected by chance -- so the bar for believing any
    single hour is much higher than it looks.
    """
    b = bars.copy()
    b["ret_bps"] = (b["close"] / b["open"] - 1) * 1e4
    g = b.groupby("hour")["ret_bps"]
    out = pd.DataFrame({"n": g.size(), "mean_bps": g.mean(), "sd": g.std()})
    out["t_stat"] = out["mean_bps"] / (out["sd"] / np.sqrt(out["n"]))
    out["up_rate"] = b.assign(u=b["ret_bps"] > 0).groupby("hour")["u"].mean()
    # Bonferroni-style threshold for 24 simultaneous tests.
    out["signif_bonferroni"] = out["t_stat"].abs() > 3.2
    return out.round(3)


def cost_floor_table(minutes: pd.DataFrame, markups=(1.0, 2.0, 3.0)) -> pd.DataFrame:
    """What stop distance is required for costs to stay a small share of risk?

    If the round-trip cost is C and you want it to consume no more than x% of
    your risk, the stop must be at least C/x.  This table is the reason the
    original strategy's 0.05-ATR minimum stop could never have worked.
    """
    m = minutes[(minutes.index.hour >= 7) & (minutes.index.hour < 21)]
    spread = m["spread_med"].median()
    rows = []
    for mk in markups:
        eff = spread * mk
        rt = eff + 0.05 + 0.02  # spread + stop slippage + entry slippage
        for share in (0.05, 0.10, 0.20):
            rows.append(
                {
                    "spread_markup": mk,
                    "round_trip_cost": round(rt, 3),
                    "cost_share_of_risk": share,
                    "min_stop_$": round(rt / share, 2),
                }
            )
    return pd.DataFrame(rows)


def run(data_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1-minute bars "
          f"{minutes.index.min()} -> {minutes.index.max()}\n")

    lm = liquidity_map(minutes)
    print("=== LIQUIDITY / COST MAP BY UTC HOUR ===")
    print(lm.to_string())
    lm.to_csv(out_dir / "liquidity_map.csv")

    print("\n=== TREND vs MEAN REVERSION ===")
    ac = autocorrelation_profile(minutes)
    print(ac.to_string(index=False))
    ac.to_csv(out_dir / "autocorrelation.csv", index=False)

    bars = add_features(resample(minutes, "60min"))
    print("\n=== HOURLY DRIFT (24 simultaneous tests) ===")
    hd = hour_of_day_drift(bars)
    print(hd.to_string())
    hd.to_csv(out_dir / "hour_drift.csv")

    print("\n=== COST FLOOR: MINIMUM VIABLE STOP ===")
    cf = cost_floor_table(minutes)
    print(cf.to_string(index=False))
    cf.to_csv(out_dir / "cost_floor.csv", index=False)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    run(Path(a.data), Path(a.out))
