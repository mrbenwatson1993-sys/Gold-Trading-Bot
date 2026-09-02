"""Walk-forward the ladder: choose the rung geometry in-sample, trade it out.

Every ladder number so far was measured on the whole history, and the winning
geometry was picked by looking at all of it. That is exactly the selection this
project has spent its time exposing elsewhere, so it gets the same treatment
here: in each fold the ladder is chosen on 12 months of training data and then
traded, untouched, on the next 3 months. Only those out-of-sample segments are
reported.

If the same geometry keeps winning its training fold, that is evidence of a
stable property. If the choice thrashes between folds while the out-of-sample
curve stays flat, the "winner" was noise.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes
from ..engine import costs as cost_presets
from ..engine.backtest import Ladder, resolve
from ..engine.metrics import bootstrap_pvalue, deflated_sharpe, summarise
from ..engine.walkforward import make_folds
from ..strategies import library as lib
from ..strategies.base import RiskSpec

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
]


def walk(minutes, tf="1h", path_tf="5min", stop_atr=2.0, min_stop=10.0,
         hold_h=72, cost=cost_presets.REALISTIC, long_only=False):
    rule = {"1h": "60min", "4h": "240min", "15min": "15min"}[tf]
    bars = add_features(resample(minutes, rule))
    path = resample(minutes, path_tf)
    folds = make_folds(bars.index, 12, 3, 3)

    oos, chosen = [], []
    for fo in folds:
        tr = bars[(bars.index >= fo.train_start) & (bars.index < fo.train_end)]
        te = bars[(bars.index >= fo.test_start) & (bars.index < fo.test_end)]
        if len(tr) < 400 or len(te) < 100:
            continue
        spec = RiskSpec(stop_atr=stop_atr, target_r=99.0, min_stop_px=min_stop,
                        max_stop_px=200.0, max_hold_h=hold_h)

        def sigs_for(frame, lad):
            s = lib.trend_pullback(frame, spec, trade_start=0, trade_end=1440)
            if long_only:
                s = [x for x in s if x.side > 0]
            for x in s:
                x.ladder = lad
            return s

        best, best_score = None, -np.inf
        for lad in LADDERS:
            s = sigs_for(tr, lad)
            if len(s) < 40:
                continue
            t, _, _ = resolve(path, s, cost)
            if len(t) < 40:
                continue
            e = t["r"].mean()
            if np.isfinite(e) and e > best_score:
                best, best_score = lad, e
        if best is None:
            continue

        t, _, _ = resolve(path, sigs_for(te, best), cost)
        if len(t):
            t = t.copy()
            t["fold"] = fo.test_start
            oos.append(t)
        chosen.append({"test_start": fo.test_start.date(), "ladder": best.name,
                       "train_E_R": round(best_score, 4)})
    return (pd.concat(oos, ignore_index=True) if oos else pd.DataFrame()), pd.DataFrame(chosen)


def report(oos, chosen, label, n_cfg):
    if oos is None or len(oos) == 0:
        print(f"{label}: no out-of-sample trades")
        return
    s = summarise(oos)
    p = bootstrap_pvalue(oos["r"].to_numpy())
    dsr = deflated_sharpe(s["sharpe"], s["n"], max(n_cfg * max(len(chosen), 1), 1))
    print(f"\n=== {label} — OUT OF SAMPLE ONLY ===")
    print(f"  n={s['n']}  E[R]={s['expectancy_r']:+.4f}  total={s['total_r']:+.1f}R  "
          f"win={s['win_rate']:.1%}  PF={s['profit_factor']:.2f}")
    print(f"  maxDD={s['max_dd_r']:.1f}R  t={s['t_stat']:+.2f}  bootstrap p={p:.4f}  "
          f"deflated Sharpe P(SR>0)={dsr:.3f}")
    print(f"  required n for t=2: {s['required_n']:.0f} (have {s['n']})")
    if len(chosen):
        vc = chosen["ladder"].value_counts()
        print(f"  ladder chosen per fold ({len(chosen)} folds):")
        for k, v in vc.items():
            print(f"     {v:>2}x  {k}")


def main(data_dir: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min().date()} -> "
          f"{minutes.index.max().date()}")
    for tf, path_tf, satr, mins, hold in (("1h", "5min", 2.0, 10.0, 72),
                                          ("4h", "15min", 3.0, 15.0, 336)):
        for lo in (False, True):
            oos, ch = walk(minutes, tf, path_tf, satr, mins, hold, long_only=lo)
            report(oos, ch, f"{tf} {'LONG-ONLY' if lo else 'both sides'}", len(LADDERS))
            if len(oos):
                oos.to_csv(out_dir / f"ladder_wf_{tf}_{'long' if lo else 'both'}.csv",
                           index=False)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out))
