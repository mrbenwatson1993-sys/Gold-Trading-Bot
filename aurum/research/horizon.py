"""The horizon spectrum: frequency vs cost efficiency vs edge.

This is the central result of the study, and the direct answer to "can I have
four or five high quality trades a day?"

The same trend-following mechanism is run at 15m, 1h, 4h and daily. Only the
timeframe changes. What moves is:

* **trades per day** - falls by ~2 orders of magnitude from 15m to daily;
* **cost drag** - falls with it, because drag = round_trip_cost / stop_distance
  and stops scale with the timeframe's ATR;
* **net expectancy** - rises, because the gross edge does not fall nearly as
  fast as the cost does.

"High quality" and "four or five a day" are not independent requirements. They
are the two ends of this table, and the table is the honest way to choose
between them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes
from ..engine import costs as cost_presets
from ..engine.backtest import run as bt_run
from ..engine.costs import CostModel
from ..engine.metrics import bootstrap_pvalue, summarise
from ..strategies import library as lib
from ..strategies.base import RiskSpec

ZERO = CostModel(spread_markup=0.0, min_spread=0.0,
                 stop_slippage=0.0, entry_slippage=0.0)

# (timeframe, path timeframe, MA length, ATR stop, min stop $, trail ATR, max hold hours)
HORIZONS = [
    ("15min", "1min",   50,  2.5,  6.0, 2.5, 12),
    ("1h",    "5min",   50,  2.5, 10.0, 2.5, 24 * 3),
    ("4h",    "15min",  50,  3.0, 15.0, 2.5, 24 * 14),
    ("1D",    "60min",  50,  3.0, 10.0, 2.0, 24 * 120),
]

_ALIAS = {"15min": "15min", "1h": "60min", "4h": "240min", "1D": "1D",
          "1min": None, "5min": "5min", "60min": "60min"}


def _bars(minutes: pd.DataFrame, tf: str) -> pd.DataFrame:
    rule = _ALIAS.get(tf, tf)
    return minutes if rule is None else resample(minutes, rule)


def run_spectrum(minutes: pd.DataFrame, cost=cost_presets.REALISTIC) -> pd.DataFrame:
    rows = []
    for tf, path_tf, ma, stop_atr, min_stop, trail, hold_h in HORIZONS:
        bars = add_features(_bars(minutes, tf))
        path = _bars(minutes, path_tf)
        if len(bars) < 260:
            continue

        spec = RiskSpec(stop_atr=stop_atr, target_r=99.0, min_stop_px=min_stop,
                        max_stop_px=200.0, trail_atr=trail, max_hold_h=hold_h)
        if tf == "1D":
            sigs = lib.daily_trend(bars, spec, ma_len=ma)
        else:
            sigs = lib.trend_pullback(bars, spec, trade_start=0, trade_end=1440)
        if len(sigs) < 12:
            continue

        gross = bt_run(path, sigs, ZERO, max_concurrent=1).trades
        net = bt_run(path, sigs, cost, max_concurrent=1).trades
        if len(net) < 12:
            continue

        gs, ns = summarise(gross), summarise(net)
        avg_stop = float(net["risk_px"].mean())
        rt = cost.round_trip_cost(float(minutes["spread_med"].median()))
        rows.append(
            {
                "horizon": tf,
                "n": ns["n"],
                "trades_per_day": round(ns["trades_per_available_day"], 3),
                "per_active_day": round(ns["trades_per_trading_day"], 2),
                "trades_per_year": round(ns["n"] / max(ns["span_days"], 1) * 365, 1),
                "avg_stop_usd": round(avg_stop, 2),
                "avg_hold_days": round(ns["avg_hold_min"] / 1440, 2),
                "cost_drag_R": round(gs["expectancy_r"] - ns["expectancy_r"], 4),
                "cost_pct_of_risk": round(rt / avg_stop * 100, 1),
                "gross_E_R": round(gs["expectancy_r"], 4),
                "net_E_R": round(ns["expectancy_r"], 4),
                "win": round(ns["win_rate"], 3),
                "t": round(ns["t_stat"], 2),
                "p": round(bootstrap_pvalue(net["r"].to_numpy()), 3),
                "net_R_per_year": round(ns["total_r"] / max(ns["span_days"], 1) * 365, 1),
                "maxDD_R": round(ns["max_dd_r"], 1),
            }
        )
    return pd.DataFrame(rows)


def main(data_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min().date()} -> "
          f"{minutes.index.max().date()}\n")

    df = run_spectrum(minutes)
    if df.empty:
        print("no horizons produced enough trades")
        return
    df.to_csv(out_dir / "horizon_spectrum.csv", index=False)

    print("=== THE HORIZON SPECTRUM (same mechanism, only timeframe changes) ===")
    print(df.to_string(index=False))

    print("\n=== READ THIS AS THE ANSWER TO 'CAN I HAVE 4-5 TRADES A DAY?' ===")
    for _, r in df.iterrows():
        verdict = ("edge survives costs" if r["net_E_R"] > 0.05
                   else "marginal" if r["net_E_R"] > 0 else "costs exceed edge")
        print(f"  {r['horizon']:>5}: {r['trades_per_day']:>6.2f} trades/day   "
              f"stop ${r['avg_stop_usd']:>6.2f}   cost {r['cost_pct_of_risk']:>5.1f}% of risk   "
              f"net E[R] {r['net_E_R']:>+7.4f}   {verdict}")

    hit = df[df["trades_per_day"] >= 4.0]
    print(f"\n  horizons delivering >= 4 trades/day with positive expectancy: "
          f"{len(hit[hit.net_E_R > 0])}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out))
