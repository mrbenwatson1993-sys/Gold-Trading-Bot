"""The frequency / quality trade-off, measured rather than assumed.

The brief was "at least four or five high quality trades every day".  Those two
requirements pull against each other, and the tension is not vague -- it is
arithmetic:

    cost drag (in R)  =  round_trip_cost / stop_distance

More trades per day normally means a shorter decision timeframe, which means a
smaller ATR, which means a smaller stop, which means *higher* cost drag on
every trade.  Going from 1 to 5 trades a day the naive way can easily triple
the cost burden per trade.

There is a way out, and it is the main design idea in this module: **decouple
the stop size from the decision timeframe**.  Take signals on 5m for
frequency, but size the stop in dollars (or as a large multiple of the 5m ATR)
so cost drag stays where a 15m stop would have put it.  The trade simply lasts
longer than the bar that triggered it.

This module sweeps that space and prints the frontier, so the choice of
operating point is explicit rather than hidden.
"""

from __future__ import annotations

import itertools
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


def _signals(bars, spec, use, ts, te, stretch=2.0):
    out = []
    if "pullback" in use:
        out += lib.trend_pullback(bars, spec, trade_start=ts, trade_end=te)
    if "sweep" in use:
        out += lib.sweep_reversal(bars, spec, trade_start=ts, trade_end=te)
    if "fade" in use:
        out += lib.stretch_fade(bars, spec, stretch_atr=stretch, trade_start=ts, trade_end=te)
    if "vwap" in use:
        out += lib.vwap_reversion(bars, spec, stretch=stretch, trade_start=ts, trade_end=te)
    if "zone" in use:
        out += lib.reaction_zone_retest(bars, spec, trade_start=ts, trade_end=te)
    return out


def sweep(
    minutes: pd.DataFrame,
    cost,
    timeframes=("5min", "15min", "30min"),
    min_stops=(3.0, 5.0, 8.0, 12.0),
    stop_atrs=(1.5, 2.5, 4.0),
    combos=(("pullback",), ("pullback", "sweep"),
            ("pullback", "sweep", "fade"),
            ("pullback", "sweep", "fade", "vwap")),
    trade_hours=((7 * 60, 20 * 60), (12 * 60, 20 * 60)),
    concurrency=(1, 2, 4),
    target_r: float = 2.0,
) -> pd.DataFrame:
    rows = []
    _sig_cache: dict = {}
    med_spread = float(minutes["spread_med"].median())
    for tf in timeframes:
        bars = add_features(resample(minutes, tf))
        if len(bars) < 500:
            continue
        for min_stop, stop_atr, use, (ts, te), conc in itertools.product(
            min_stops, stop_atrs, combos, trade_hours, concurrency
        ):
            spec = RiskSpec(
                stop_atr=stop_atr, target_r=target_r,
                min_stop_px=min_stop, max_stop_px=40.0,
                entry_retrace=0.0, max_hold_h=12.0,
            )
            key = (tf, min_stop, stop_atr, use, ts, te)
            if key not in _sig_cache:
                _sig_cache[key] = _signals(bars, spec, use, ts, te)
            sigs = _sig_cache[key]
            if len(sigs) < 40:
                continue
            res = bt_run(minutes, sigs, cost, max_concurrent=conc,
                         max_daily_loss_r=3.0)
            if len(res.trades) < 40:
                continue
            s = summarise(res.trades)
            avg_stop = float(res.trades["risk_px"].mean())
            rows.append(
                {
                    "tf": tf,
                    "strategies": "+".join(use),
                    "stop_atr": stop_atr,
                    "min_stop": min_stop,
                    "hours": f"{ts // 60:02d}-{te // 60:02d}",
                    "conc": conc,
                    "n": s["n"],
                    "trades_per_day": round(s["trades_per_trading_day"], 2),
                    "avg_stop_usd": round(avg_stop, 2),
                    "cost_pct_of_risk": round(
                        cost.round_trip_cost(med_spread) / avg_stop * 100, 1),
                    "E_R": round(s["expectancy_r"], 4),
                    "win": round(s["win_rate"], 3),
                    "t": round(s["t_stat"], 2),
                    "R_per_year": round(s["total_r"] / max(s["span_days"], 1) * 365, 1),
                    "maxDD_R": round(s["max_dd_r"], 1),
                    "avg_hold_min": round(s["avg_hold_min"], 0),
                }
            )
    return pd.DataFrame(rows)


def frontier(df: pd.DataFrame, min_trades_per_day: float = 4.0) -> pd.DataFrame:
    """Configurations that meet the frequency brief, ranked by expectancy."""
    if df is None or len(df) == 0:
        return pd.DataFrame()
    hit = df[df["trades_per_day"] >= min_trades_per_day]
    return hit.sort_values("E_R", ascending=False)


def main(data_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min()} -> {minutes.index.max()}\n")

    df = sweep(minutes, cost_presets.REALISTIC)
    if df.empty:
        print("no configurations produced enough trades")
        return
    df.to_csv(out_dir / "frequency_sweep.csv", index=False)

    print("=== COST DRAG vs STOP SIZE (why frequency is expensive) ===")
    g = df.groupby(["tf", "min_stop"]).agg(
        avg_stop=("avg_stop_usd", "mean"),
        cost_pct=("cost_pct_of_risk", "mean"),
        E_R=("E_R", "mean"),
        tr_day=("trades_per_day", "mean"),
    ).round(3)
    print(g.to_string())

    print("\n=== TOP 15 BY EXPECTANCY (any frequency) ===")
    print(df.sort_values("E_R", ascending=False).head(15).to_string(index=False))

    for target in (3.0, 4.0, 5.0):
        f = frontier(df, target)
        print(f"\n=== CONFIGS ACHIEVING >= {target:.0f} TRADES/DAY ===")
        if f.empty:
            print("  none")
        else:
            print(f.head(10).to_string(index=False))
            best = f.iloc[0]
            print(f"  best E[R] at this frequency: {best['E_R']:+.4f} "
                  f"({best['tf']}, {best['strategies']}, stop ~${best['avg_stop_usd']})")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out))
