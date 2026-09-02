"""Performance statistics with honest significance testing.

The point of this module is to make it hard to fool ourselves.  Every headline
number is paired with a measure of how much of it could be luck:

* ``bootstrap_pvalue`` - resample the trade sequence to ask how often a random
  reordering beats the observed mean R.  This is the standard test for "is
  this expectancy distinguishable from zero".
* ``deflated_sharpe`` - Bailey & Lopez de Prado's correction for having tried
  many strategy variants.  A Sharpe of 1.5 found after 200 trials is not the
  same as a Sharpe of 1.5 found on the first try.
* ``required_n`` - the sample size that *would* be needed to call the observed
  expectancy real.  Usually the most sobering number on the page.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def summarise(trades: pd.DataFrame, label: str = "") -> dict:
    if trades is None or len(trades) == 0:
        return {"label": label, "n": 0}

    r = trades["r"].to_numpy(np.float64)
    n = len(r)
    wins = r > 0
    mean_r = r.mean()
    sd_r = r.std(ddof=1) if n > 1 else np.nan

    gross_win = r[wins].sum()
    gross_loss = -r[~wins].sum()

    equity = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))
    dd = peak[1:] - equity
    max_dd = dd.max() if n else 0.0

    # Trades/day over the *calendar* span actually traded.
    span_days = 1
    if "entry_dt" in trades:
        span = trades["entry_dt"].max() - trades["entry_dt"].min()
        span_days = max(span.days, 1)
    trading_days = trades["entry_dt"].dt.normalize().nunique() if "entry_dt" in trades else 1

    # Sharpe on the per-trade R series, annualised by trades per year.
    tpy = n / max(span_days, 1) * 365.0
    sharpe = (mean_r / sd_r * np.sqrt(tpy)) if sd_r and sd_r > 0 else np.nan

    # Two different "per day" numbers, both useful and easy to confuse:
    #   per ACTIVE day  = n / days on which we traded at all
    #   per AVAILABLE day = n / weekday sessions in the span   <- the one that
    # answers "how many trades will I see in a typical day", and the one a
    # frequency target should be measured against.
    available_days = max(span_days * 5.0 / 7.0, 1.0)

    return {
        "label": label,
        "n": n,
        "expectancy_r": mean_r,
        "sd_r": sd_r,
        "total_r": r.sum(),
        "win_rate": wins.mean(),
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else np.inf,
        "max_dd_r": max_dd,
        "return_over_dd": r.sum() / max_dd if max_dd > 0 else np.inf,
        "sharpe": sharpe,
        "trades_per_trading_day": n / max(trading_days, 1),   # per ACTIVE day
        "trades_per_available_day": n / available_days,
        "trades_per_year": n / max(span_days, 1) * 365.0,
        "trading_days": trading_days,
        "span_days": span_days,
        "avg_hold_min": trades["hold_min"].mean() if "hold_min" in trades else np.nan,
        "t_stat": mean_r / (sd_r / np.sqrt(n)) if sd_r and sd_r > 0 else np.nan,
        "required_n": required_n(mean_r, sd_r),
    }


def required_n(mean_r: float, sd_r: float, t_target: float = 2.0) -> float:
    """Trades needed for this expectancy to reach |t| = t_target."""
    if not sd_r or sd_r <= 0 or mean_r == 0 or np.isnan(mean_r) or np.isnan(sd_r):
        return np.inf
    return float((t_target * sd_r / abs(mean_r)) ** 2)


def bootstrap_pvalue(r: np.ndarray, iters: int = 20_000, seed: int = 7) -> float:
    """One-sided p-value that mean(R) > 0, by sign-flip permutation."""
    r = np.asarray(r, dtype=np.float64)
    if len(r) < 5:
        return np.nan
    rng = np.random.default_rng(seed)
    observed = r.mean()
    signs = rng.choice([-1.0, 1.0], size=(iters, len(r)))
    null = (signs * np.abs(r)).mean(axis=1)
    return float((null >= observed).mean())


def deflated_sharpe(sharpe: float, n: int, trials: int, skew: float = 0.0,
                    kurt: float = 3.0) -> float:
    """Bailey & Lopez de Prado deflated Sharpe ratio probability.

    Returns P(true Sharpe > 0) after correcting for ``trials`` variants tried.
    """
    if n < 10 or np.isnan(sharpe) or trials < 1:
        return np.nan
    e = 0.5772156649
    # Expected max Sharpe under the null across `trials` independent trials.
    z1 = stats.norm.ppf(1 - 1.0 / trials) if trials > 1 else 0.0
    z2 = stats.norm.ppf(1 - 1.0 / (trials * np.e)) if trials > 1 else 0.0
    sr0 = (1 - e) * z1 + e * z2
    denom = np.sqrt(1 - skew * sharpe + (kurt - 1) / 4.0 * sharpe**2)
    if denom <= 0:
        return np.nan
    return float(stats.norm.cdf((sharpe - sr0) * np.sqrt(n - 1) / denom))


def by_bucket(trades: pd.DataFrame, col: str) -> pd.DataFrame:
    """Expectancy broken out by a column - for finding where an edge lives."""
    if trades is None or len(trades) == 0 or col not in trades:
        return pd.DataFrame()
    g = trades.groupby(col)["r"]
    out = pd.DataFrame(
        {
            "n": g.size(),
            "expectancy_r": g.mean(),
            "total_r": g.sum(),
            "win_rate": trades.groupby(col)["r"].apply(lambda s: (s > 0).mean()),
        }
    )
    return out.sort_values("total_r", ascending=False)


def format_summary(s: dict) -> str:
    if s.get("n", 0) == 0:
        return f"{s.get('label','')}: no trades"
    return (
        f"{s['label']:<28} n={s['n']:>5}  "
        f"E[R]={s['expectancy_r']:+.4f}  "
        f"tot={s['total_r']:+8.1f}R  "
        f"win={s['win_rate']:.1%}  "
        f"PF={s['profit_factor']:.2f}  "
        f"maxDD={s['max_dd_r']:.1f}R  "
        f"t={s['t_stat']:+.2f}  "
        f"tr/day={s['trades_per_trading_day']:.2f}"
    )
