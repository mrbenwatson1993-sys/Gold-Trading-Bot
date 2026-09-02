"""Multi-timeframe ladder test: does the ratchet help where an edge exists?

The 15-minute sweep showed the ladder roughly halving the loss per trade versus
a fixed target, without ever crossing zero -- because the entry it was sitting
on had no edge to protect. The interesting question is what it does at the
horizons where the study *did* find an edge (4-hour and daily), and whether the
best rung geometry is stable across timeframes or has to be refitted at each
one. A geometry that only works at one timeframe is a fitted parameter; one
that holds across all four is a property of the market's path structure.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes
from ..engine import costs as cost_presets
from ..engine.backtest import MARKET, Ladder, Signal, resolve
from ..engine.metrics import bootstrap_pvalue, summarise
from ..strategies import library as lib
from ..strategies.base import RiskSpec

# (decision tf, fill path, stop ATR, min stop $, max hold hours, MA for daily)
HORIZONS = [
    ("15min", "1min",  2.0,   6.0,   24, None),
    ("1h",    "5min",  2.0,  10.0,   72, None),
    ("4h",    "15min", 3.0,  15.0,  336, None),
    ("1D",    "60min", 3.0,  10.0, 2880, 50),
]

LADDERS = [
    Ladder(target_r=2.0),
    Ladder(target_r=3.0),
    Ladder(steps=((1.0, 0.0),)),
    Ladder(steps=((1.0, 0.0), (2.0, 1.0))),
    Ladder(steps=((1.0, 0.0), (3.0, 1.5))),
    Ladder(steps=((1.0, 0.0), (2.0, 0.8), (3.0, 1.8))),
    Ladder(steps=((1.5, 0.0), (3.0, 1.5), (5.0, 3.2))),
    Ladder(trail_atr=2.5),
    Ladder(trail_atr=4.0),
    Ladder(give_back_frac=0.5),
    Ladder(steps=((1.0, 0.0), (3.0, 1.5)), trail_atr=3.0),
]

_ALIAS = {"15min": "15min", "1h": "60min", "4h": "240min", "1D": "1D",
          "1min": None, "5min": "5min", "15min_p": "15min", "60min": "60min"}


def _bars(minutes, tf):
    rule = _ALIAS.get(tf, tf)
    return minutes if rule is None else resample(minutes, rule)


def run(data_dir: Path, out_dir: Path, cost=cost_presets.REALISTIC) -> pd.DataFrame:
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min().date()} -> "
          f"{minutes.index.max().date()}\n")
    rows = []
    for tf, path_tf, stop_atr, min_stop, hold_h, ma in HORIZONS:
        bars = add_features(_bars(minutes, tf))
        path = _bars(minutes, path_tf)
        if len(bars) < 300:
            continue
        for lad in LADDERS:
            spec = RiskSpec(stop_atr=stop_atr, target_r=99.0, min_stop_px=min_stop,
                            max_stop_px=200.0, max_hold_h=hold_h)
            sigs = (lib.daily_trend(bars, spec, ma_len=ma) if ma
                    else lib.trend_pullback(bars, spec, trade_start=0, trade_end=1440))
            for s in sigs:
                s.ladder = lad
            if len(sigs) < 25:
                continue
            t, _, _ = resolve(path, sigs, cost)
            if len(t) < 25:
                continue
            s_ = summarise(t)
            rows.append({
                "tf": tf, "ladder": lad.name, "n": s_["n"],
                "E_R": round(s_["expectancy_r"], 4),
                "win": round(s_["win_rate"], 3),
                "PF": round(s_["profit_factor"], 3),
                "total_R": round(s_["total_r"], 1),
                "maxDD_R": round(s_["max_dd_r"], 1),
                "t": round(s_["t_stat"], 2),
                "p": round(bootstrap_pvalue(t["r"].to_numpy()), 4),
                "hold_h": round(s_["avg_hold_min"] / 60, 1),
            })
        print(f"  {tf}: {len([r for r in rows if r['tf']==tf])} ladder variants tested", flush=True)

    df = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "ladder_mtf.csv", index=False)
    return df


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    df = run(Path(a.data), Path(a.out))
    for tf in df["tf"].unique():
        sub = df[df.tf == tf].sort_values("E_R", ascending=False)
        print(f"\n=== {tf} ===")
        print(sub.drop(columns=["tf"]).to_string(index=False))
