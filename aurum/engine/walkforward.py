"""Walk-forward evaluation.

The single most important guard against fooling ourselves.  Instead of fitting
parameters on all the data and reporting the fit, we repeatedly:

    fit on [t0, t1)   ->   trade the best config on [t1, t2)   ->   roll forward

and staple together only the *out-of-sample* segments.  The resulting equity
curve is the closest honest analogue of what live trading would have produced,
because at every point the parameters were chosen using only prior data.

A strategy that looks good in-sample and flat out-of-sample is not a strategy
that needs more tuning -- it is a strategy that was never there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from .backtest import BacktestResult, Signal, run
from .costs import CostModel
from .metrics import summarise


@dataclass
class Fold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def make_folds(
    index: pd.DatetimeIndex,
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
) -> list[Fold]:
    """Rolling anchored folds across the available history."""
    start, end = index.min().normalize(), index.max().normalize()
    folds: list[Fold] = []
    cur = start
    while True:
        tr_end = cur + pd.DateOffset(months=train_months)
        te_end = tr_end + pd.DateOffset(months=test_months)
        if te_end > end:
            break
        folds.append(Fold(cur, tr_end, tr_end, te_end))
        cur = cur + pd.DateOffset(months=step_months)
    return folds


def _slice(df: pd.DataFrame, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
    return df[(df.index >= a) & (df.index < b)]


def walk_forward(
    decision_bars: pd.DataFrame,
    minutes: pd.DataFrame,
    signal_fn: Callable[[pd.DataFrame, dict], list[Signal]],
    grid: Iterable[dict],
    costs: CostModel,
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
    objective: str = "expectancy_r",
    min_train_trades: int = 40,
    warmup_bars: int = 250,
) -> tuple[pd.DataFrame, list[dict]]:
    """Return (out-of-sample trades, per-fold chosen configs)."""
    grid = list(grid)
    folds = make_folds(decision_bars.index, train_months, test_months, step_months)
    oos_frames: list[pd.DataFrame] = []
    chosen: list[dict] = []

    for fold in folds:
        # Warmup: indicators need history, so feed extra bars before the window
        # but only *emit* signals inside it.
        train = _slice(decision_bars, fold.train_start, fold.train_end)
        test = _slice(decision_bars, fold.test_start, fold.test_end)
        if len(train) < warmup_bars or len(test) < warmup_bars // 2:
            continue

        best, best_score = None, -np.inf
        for params in grid:
            sigs = signal_fn(train, params)
            if not sigs:
                continue
            res = run(minutes, sigs, costs)
            if len(res.trades) < min_train_trades:
                continue
            s = summarise(res.trades)
            score = s.get(objective, -np.inf)
            if score is not None and np.isfinite(score) and score > best_score:
                best, best_score = params, score

        if best is None:
            continue

        test_sigs = signal_fn(test, best)
        if not test_sigs:
            continue
        test_res = run(minutes, test_sigs, costs)
        if len(test_res.trades):
            t = test_res.trades.copy()
            t["fold_test_start"] = fold.test_start
            oos_frames.append(t)
        chosen.append(
            {
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "train_score": best_score,
                **{f"p_{k}": v for k, v in best.items()},
            }
        )

    oos = pd.concat(oos_frames, ignore_index=True) if oos_frames else pd.DataFrame()
    return oos, chosen
