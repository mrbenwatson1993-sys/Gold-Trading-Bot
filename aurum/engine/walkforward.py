"""Rolling train/test folds.

The single most important guard against fooling ourselves.  Instead of fitting
parameters on all the data and reporting the fit, we repeatedly:

    fit on [t0, t1)   ->   trade the best config on [t1, t2)   ->   roll forward

and staple together only the *out-of-sample* segments.  The resulting equity
curve is the closest honest analogue of what live trading would have produced,
because at every point the parameters were chosen using only prior data.

A strategy that looks good in-sample and flat out-of-sample is not a strategy
that needs more tuning -- it is a strategy that was never there.

Fold construction lives here; the selection loop that consumes these folds is
in ``aurum.research.validate``, where it sits next to the parameter grid it
searches.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Fold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp

    @property
    def label(self) -> str:
        return f"{self.test_start.date()}..{self.test_end.date()}"


def make_folds(
    index: pd.DatetimeIndex,
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
) -> list[Fold]:
    """Rolling folds across the available history.

    Anchored at the start and stepped forward, so every test window is strictly
    later than the data used to choose its parameters.  Folds that would run
    past the end of the data are dropped rather than truncated: a short final
    window produces a noisy result that is easy to over-read.
    """
    if len(index) == 0:
        return []
    start, end = index.min().normalize(), index.max().normalize()

    folds: list[Fold] = []
    cur = start
    while True:
        train_end = cur + pd.DateOffset(months=train_months)
        test_end = train_end + pd.DateOffset(months=test_months)
        if test_end > end:
            break
        folds.append(Fold(cur, train_end, train_end, test_end))
        cur = cur + pd.DateOffset(months=step_months)
    return folds
