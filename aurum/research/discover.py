"""Open-ended edge discovery with multiple-testing control.

The brief was to look past textbook patterns at what is actually in the data:
time-of-day anomalies, activity/order-flow structure, volatility shifts. This
module does that systematically rather than by inspection.

Protocol
--------
1. Build a wide feature set from raw 1-minute structure -- tick intensity,
   spread stress, intrabar efficiency, absorption, run structure, volatility
   regime, session clock -- all strictly causal.
2. Measure **forward** returns in ATR units (so a 2021 move and a 2025 move are
   comparable) over several horizons.
3. Split features into quintiles; the effect is the top-minus-bottom spread.
4. Sample **non-overlapping** forward windows, because overlapping forward
   returns are autocorrelated and inflate t-statistics badly -- this is the
   single most common way feature mining lies.
5. Discover on the first 60% of history, then require the *same sign* on the
   held-out 40%.
6. Apply Benjamini-Hochberg FDR across every test performed, so the reported
   survivors are corrected for how many things were tried.

A feature that clears all six is worth building on. Most will not, and that is
the point: the machinery exists to make it hard to fool ourselves.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------
def build_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Causal features. Everything at bar i uses only bars <= i."""
    d = bars.copy()
    eps = 1e-12

    rng = (d["high"] - d["low"]).replace(0, np.nan)
    body = (d["close"] - d["open"]).abs()
    atr = d["atr14"].replace(0, np.nan)

    # --- activity / order-flow proxies -------------------------------------
    # Tick count is the closest thing to volume in spot gold, and the ratio of
    # activity to the range it produced is informative in itself.
    tick_base = d["ticks"].rolling(96, min_periods=24).median()
    d["f_tick_intensity"] = d["ticks"] / tick_base.replace(0, np.nan)

    # Absorption: lots of activity, little price movement. Someone is filling
    # size without letting price go -- classically a precursor to a reversal.
    d["f_absorption"] = (d["ticks"] / tick_base.replace(0, np.nan)) / (rng / atr + eps)

    # Impulse: activity AND range together.
    d["f_impulse"] = (d["ticks"] / tick_base.replace(0, np.nan)) * (rng / atr)

    # Cost per unit of movement -- when this is high the bar is expensive noise.
    d["f_spread_per_range"] = d["spread_med"] / (rng + eps)

    # Spread stress vs the same hour's own baseline, so it flags dislocation
    # rather than re-discovering that the Asian session is thin.
    hourly = d.groupby(d.index.hour)["spread_med"]
    d["f_spread_stress"] = d["spread_med"] / hourly.transform(
        lambda x: x.rolling(480, min_periods=60).median()
    ).replace(0, np.nan)

    # --- structure ----------------------------------------------------------
    d["f_efficiency"] = body / rng                      # conviction vs churn
    d["f_upper_wick"] = (d["high"] - d[["open", "close"]].max(axis=1)) / rng
    d["f_lower_wick"] = (d[["open", "close"]].min(axis=1) - d["low"]) / rng
    d["f_wick_skew"] = d["f_upper_wick"] - d["f_lower_wick"]

    # Directional efficiency: net move divided by path length. High = clean
    # trend, low = chop covering the same ground repeatedly.
    for n in (6, 24):
        net = (d["close"] - d["close"].shift(n)).abs()
        path = d["close"].diff().abs().rolling(n).sum()
        d[f"f_dir_eff{n}"] = net / path.replace(0, np.nan)

    # --- volatility regime --------------------------------------------------
    d["f_atr_ratio"] = d["atr_ratio"]
    d["f_vol_of_vol"] = (d["atr14"].pct_change().rolling(24).std())
    d["f_vol_shift"] = d["atr14"] / d["atr14"].shift(24).replace(0, np.nan)
    d["f_range_z"] = (rng - rng.rolling(96).mean()) / rng.rolling(96).std().replace(0, np.nan)

    # --- position / extension ----------------------------------------------
    d["f_ext_ema50"] = (d["close"] - d["ema50"]) / atr
    d["f_close_loc"] = (d["close"] - d["low"]) / rng      # where in the bar we closed
    d["f_rsi"] = d["rsi14"]

    # --- run structure ------------------------------------------------------
    up = (d["close"] > d["open"]).astype(int)
    grp = (up != up.shift()).cumsum()
    d["f_run_len"] = up.groupby(grp).cumcount() + 1
    d["f_run_signed"] = d["f_run_len"] * np.where(up == 1, 1, -1)

    # --- session clock ------------------------------------------------------
    d["f_hour"] = d.index.hour
    d["f_dow"] = d.index.dayofweek

    return d


FEATURES = [
    "f_tick_intensity", "f_absorption", "f_impulse", "f_spread_per_range",
    "f_spread_stress", "f_efficiency", "f_wick_skew", "f_dir_eff6",
    "f_dir_eff24", "f_atr_ratio", "f_vol_of_vol", "f_vol_shift", "f_range_z",
    "f_ext_ema50", "f_close_loc", "f_rsi", "f_run_signed",
]


# ---------------------------------------------------------------------------
# Forward returns and testing
# ---------------------------------------------------------------------------
def forward_returns(d: pd.DataFrame, horizons=(4, 16, 48)) -> pd.DataFrame:
    """Forward return over k bars, normalised by ATR at the decision bar."""
    out = d.copy()
    for k in horizons:
        out[f"fwd{k}"] = (out["close"].shift(-k) - out["close"]) / out["atr14"]
    return out


def _nonoverlapping(idx: np.ndarray, k: int) -> np.ndarray:
    """Thin a boolean-selected index so forward windows do not overlap."""
    keep, last = [], -10**9
    for i in idx:
        if i - last >= k:
            keep.append(i)
            last = i
    return np.array(keep, dtype=int)


def test_feature(d: pd.DataFrame, feature: str, horizon: int,
                 n_bins: int = 5, min_n: int = 60) -> dict | None:
    """Quintile top-minus-bottom spread in forward return, non-overlapping."""
    col, fwd = d[feature], d[f"fwd{horizon}"]
    ok = col.notna() & fwd.notna() & np.isfinite(col) & np.isfinite(fwd)
    if ok.sum() < min_n * n_bins:
        return None

    sub = d.loc[ok]
    try:
        q = pd.qcut(sub[feature], n_bins, labels=False, duplicates="drop")
    except ValueError:
        return None
    if q.nunique() < n_bins:
        return None

    pos = np.arange(len(d))[ok.to_numpy()]
    top_mask = (q == q.max()).to_numpy()
    bot_mask = (q == q.min()).to_numpy()

    top = _nonoverlapping(pos[top_mask], horizon)
    bot = _nonoverlapping(pos[bot_mask], horizon)
    if len(top) < min_n or len(bot) < min_n:
        return None

    a = d[f"fwd{horizon}"].to_numpy()[top]
    b = d[f"fwd{horizon}"].to_numpy()[bot]
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < min_n or len(b) < min_n:
        return None

    t, p = stats.ttest_ind(a, b, equal_var=False)
    return {
        "feature": feature, "horizon": horizon,
        "n_top": len(a), "n_bot": len(b),
        "mean_top": a.mean(), "mean_bot": b.mean(),
        "spread": a.mean() - b.mean(),
        "t": t, "p": p,
    }


def benjamini_hochberg(p: np.ndarray, q: float = 0.10) -> np.ndarray:
    """Return a boolean mask of discoveries at FDR level q."""
    p = np.asarray(p, dtype=float)
    n = len(p)
    order = np.argsort(p)
    thresh = q * (np.arange(1, n + 1) / n)
    passed = p[order] <= thresh
    if not passed.any():
        return np.zeros(n, bool)
    cutoff = np.max(np.where(passed)[0])
    mask = np.zeros(n, bool)
    mask[order[: cutoff + 1]] = True
    return mask


def run_discovery(minutes: pd.DataFrame, tf: str = "15min",
                  horizons=(4, 16, 48), train_frac: float = 0.6,
                  fdr_q: float = 0.10) -> pd.DataFrame:
    bars = forward_returns(build_features(add_features(resample(minutes, tf))), horizons)
    split = bars.index[int(len(bars) * train_frac)]
    train, test = bars[bars.index < split], bars[bars.index >= split]

    rows = []
    for f in FEATURES:
        for h in horizons:
            r = test_feature(train, f, h)
            if r is None:
                continue
            r["set"] = "train"
            confirm = test_feature(test, f, h)
            r["test_spread"] = confirm["spread"] if confirm else np.nan
            r["test_t"] = confirm["t"] if confirm else np.nan
            r["same_sign"] = (
                bool(confirm and np.sign(confirm["spread"]) == np.sign(r["spread"]))
            )
            rows.append(r)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["fdr_pass"] = benjamini_hochberg(df["p"].to_numpy(), fdr_q)
    df["survivor"] = df["fdr_pass"] & df["same_sign"]
    return df.sort_values("p")


def main(data_dir: Path, out_dir: Path, tf: str = "15min") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min().date()} -> "
          f"{minutes.index.max().date()}")

    df = run_discovery(minutes, tf)
    if df.empty:
        print("no testable features")
        return
    df.to_csv(out_dir / f"discovery_{tf}.csv", index=False)

    cols = ["feature", "horizon", "n_top", "n_bot", "spread", "t", "p",
            "test_spread", "test_t", "same_sign", "fdr_pass", "survivor"]
    print(f"\n=== ALL TESTS ({len(df)} features x horizons), sorted by p ===")
    print(df[cols].head(20).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    surv = df[df["survivor"]]
    print(f"\n=== SURVIVORS: FDR q=0.10 AND same sign out-of-sample ===")
    if surv.empty:
        print("  none. Every apparent effect is either inside the multiple-testing")
        print("  budget or fails to reproduce on held-out data.")
    else:
        print(surv[cols].to_string(index=False, float_format=lambda x: f"{x:8.4f}"))
        print("\n  Effect sizes are in ATR units of forward move. Compare against")
        print("  a round-trip cost of roughly 0.05-0.15 ATR at these horizons")
        print("  before treating any of them as tradeable.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--tf", default="15min")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out), a.tf)
