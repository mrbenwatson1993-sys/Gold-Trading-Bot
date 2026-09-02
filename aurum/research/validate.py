"""Rigorous out-of-sample validation of a surviving mechanism.

The screen in ``hypotheses.py`` uses one train/test split, which is enough to
kill bad ideas but not enough to trust a good one: a single split can flatter a
strategy that happened to suit that particular test period.

This module runs the full protocol:

* **Walk-forward** - 12 months train, 3 months test, rolled quarterly.  Only
  out-of-sample segments are stitched into the reported equity curve.
* **Parameter stability** - the configuration chosen in each fold is printed.
  A mechanism whose optimal parameters jump wildly between folds is fitting
  noise even if its out-of-sample curve looks acceptable.
* **Deflated Sharpe** - corrected for how many configurations were searched.
* **Cost sensitivity** - the same walk-forward re-run at three cost levels.
  A strategy that only survives at optimistic costs is not deployable.
* **Regime breakdown** - performance by year and by volatility regime, so a
  result driven entirely by one bull run is visible.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes
from ..engine import costs as cost_presets
from ..engine.backtest import run as bt_run
from ..engine.metrics import (
    bootstrap_pvalue,
    by_bucket,
    deflated_sharpe,
    format_summary,
    summarise,
)
from ..engine.walkforward import make_folds
from ..strategies import library as lib
from ..strategies.base import RiskSpec


def _spec(p: dict) -> RiskSpec:
    return RiskSpec(
        stop_atr=p["stop_atr"],
        target_r=p["target_r"],
        min_stop_px=p["min_stop"],
        max_stop_px=40.0,
        entry_retrace=p.get("entry_retrace", 0.0),
        breakeven_r=p.get("breakeven_r", 0.0),
        trail_atr=p.get("trail_atr", 0.0),
        expiry_min=45,
        max_hold_h=p.get("hold_h", 12.0),
    )


def build_signals(bars: pd.DataFrame, p: dict) -> list:
    """The production signal set: whichever mechanisms survived the screen.

    ``p`` selects which sub-strategies are active so the walk-forward can
    choose the mix per fold rather than us fixing it by hand.
    """
    spec = _spec(p)
    sigs = []
    ts, te = p["trade_start"], p["trade_end"]
    mix = p.get("mix", "pullback")
    if "pullback" in mix:
        sigs += lib.trend_pullback(bars, spec, trade_start=ts, trade_end=te)
    if "fade" in mix:
        sigs += lib.stretch_fade(bars, spec, stretch_atr=p.get("stretch", 2.0),
                                 trade_start=ts, trade_end=te)
    if "expansion" in mix:
        sigs += lib.volatility_expansion(bars, spec, trade_start=ts, trade_end=te)
    if "sweep" in mix:
        sigs += lib.sweep_reversal(bars, spec, trade_start=ts, trade_end=te)
    return sigs


def grid(**kw):
    keys = list(kw)
    for combo in itertools.product(*(kw[k] for k in keys)):
        yield dict(zip(keys, combo))


def walk_forward(
    minutes: pd.DataFrame,
    tf: str,
    param_grid: list[dict],
    cost,
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
    min_train_trades: int = 50,
    max_concurrent: int = 2,
    max_daily_loss_r: float | None = 3.0,
    objective: str = "expectancy_r",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = add_features(resample(minutes, tf))
    folds = make_folds(bars.index, train_months, test_months, step_months)
    oos, chosen = [], []

    for fold in folds:
        train = bars[(bars.index >= fold.train_start) & (bars.index < fold.train_end)]
        test = bars[(bars.index >= fold.test_start) & (bars.index < fold.test_end)]
        if len(train) < 500 or len(test) < 100:
            continue

        best_p, best_score, best_n = None, -np.inf, 0
        for p in param_grid:
            sigs = build_signals(train, p)
            if len(sigs) < min_train_trades:
                continue
            r = bt_run(minutes, sigs, cost, max_concurrent=max_concurrent,
                       max_daily_loss_r=max_daily_loss_r)
            if len(r.trades) < min_train_trades:
                continue
            s = summarise(r.trades)
            score = s.get(objective, -np.inf)
            if np.isfinite(score) and score > best_score:
                best_p, best_score, best_n = p, score, s["n"]

        if best_p is None:
            continue

        tr = bt_run(minutes, build_signals(test, best_p), cost,
                    max_concurrent=max_concurrent, max_daily_loss_r=max_daily_loss_r)
        if len(tr.trades):
            t = tr.trades.copy()
            t["fold"] = fold.test_start
            oos.append(t)
        chosen.append({"test_start": fold.test_start.date(),
                       "test_end": fold.test_end.date(),
                       "train_E_R": round(best_score, 4), "train_n": best_n,
                       **best_p})

    oos_df = pd.concat(oos, ignore_index=True) if oos else pd.DataFrame()
    return oos_df, pd.DataFrame(chosen)


def report(oos: pd.DataFrame, chosen: pd.DataFrame, n_configs: int, label: str) -> dict:
    if oos is None or len(oos) == 0:
        print(f"\n{label}: no out-of-sample trades")
        return {}
    s = summarise(oos, label)
    p = bootstrap_pvalue(oos["r"].to_numpy())
    dsr = deflated_sharpe(s["sharpe"], s["n"], max(n_configs * max(len(chosen), 1), 1))
    print(f"\n=== {label} (OUT OF SAMPLE ONLY) ===")
    print(format_summary(s))
    print(f"  bootstrap p(E[R]>0) = {p:.4f}   deflated Sharpe P(SR>0) = {dsr:.3f}"
          f"   configs searched = {n_configs}")
    print(f"  required n for t=2: {s['required_n']:.0f}  (have {s['n']})")
    return {**s, "p_value": p, "deflated_sharpe": dsr}


def by_year(oos: pd.DataFrame) -> pd.DataFrame:
    if oos is None or len(oos) == 0:
        return pd.DataFrame()
    d = oos.copy()
    d["year"] = d["entry_dt"].dt.year
    return by_bucket(d, "year")


def main(data_dir: Path, out_dir: Path, tf: str = "15min") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min()} -> {minutes.index.max()}")

    # 48 configurations. Kept small on purpose: the more the walk-forward
    # searches, the more likely its per-fold winner is the luckiest rather
    # than the best, which is exactly what deflated Sharpe penalises.
    param_grid = [
        dict(stop_atr=2.5, min_stop=ms, target_r=tr, trail_atr=ta,
             mix=mix, trade_start=w[0], trade_end=w[1])
        for ms in (6.0, 10.0)
        for tr in (2.0, 3.0)
        for ta in (0.0, 2.5)
        for mix in ("pullback", "pullback+fade")
        for w in ((7 * 60, 20 * 60), (12 * 60, 20 * 60), (12 * 60, 16 * 60))
    ]
    print(f"walk-forward over {len(param_grid)} configs per fold, tf={tf}")

    results = {}
    for name, cost in (("TIGHT", cost_presets.TIGHT),
                       ("REALISTIC", cost_presets.REALISTIC),
                       ("HARSH", cost_presets.HARSH)):
        oos, chosen = walk_forward(minutes, tf, param_grid, cost)
        results[name] = report(oos, chosen, len(param_grid), f"{tf} @ {name} costs")
        if name == "REALISTIC" and len(oos):
            oos.to_csv(out_dir / f"oos_trades_{tf}.csv", index=False)
            chosen.to_csv(out_dir / f"wf_params_{tf}.csv", index=False)
            print("\n  chosen config per fold (parameter stability):")
            print(chosen.to_string(index=False))
            print("\n  out-of-sample by year:")
            print(by_year(oos).to_string())

    pd.DataFrame(results).T.to_csv(out_dir / f"validation_{tf}.csv")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--tf", default="15min")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out), a.tf)
