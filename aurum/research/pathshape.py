"""What is predictable when direction is not: volatility, and path shape.

The discovery pass tested 153 feature/horizon combinations for *directional*
predictability and produced zero survivors. That is a real result, and it
redirects the work rather than ending it, because a step-trailing ("ladder")
exit is not a bet on direction. It is a bet on **path shape** -- on how far a
position travels in your favour before it comes back.

Two things are worth measuring before designing any ladder:

**Volatility predictability.** Volatility clusters; it is among the most robust
regularities in markets. If tomorrow's range is forecastable from today's, then
stop distances and step sizes should scale with it rather than being fixed.

**MFE / MAE structure.** For a position held from an arbitrary entry, the joint
distribution of maximum favourable and maximum adverse excursion tells you
exactly where a ladder's rungs should sit. Placing a breakeven trigger at 1R is
a guess; placing it where the data says the favourable excursion usually stalls
is a design decision.

Both are measured on random entries as well as signal entries, so we can see
what comes from the market's path structure rather than from any signal.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes


# ---------------------------------------------------------------------------
# 1. Volatility predictability
# ---------------------------------------------------------------------------
def volatility_predictability(bars: pd.DataFrame, horizons=(1, 4, 16, 48)) -> pd.DataFrame:
    """Does current realised range predict future realised range?

    Reported as the R^2 of a log-log regression of future ATR on current ATR.
    Compare against the directional tests, which produced nothing.
    """
    rows = []
    atr = bars["atr14"]
    for k in horizons:
        fut = atr.shift(-k)
        ok = (atr > 0) & (fut > 0) & atr.notna() & fut.notna()
        x, y = np.log(atr[ok]), np.log(fut[ok])
        if len(x) < 500:
            continue
        # Thin to non-overlapping samples so R^2 is not inflated by overlap.
        step = max(k, 1)
        x, y = x.to_numpy()[::step], y.to_numpy()[::step]
        sl, ic, r, p, se = stats.linregress(x, y)
        rows.append({"horizon_bars": k, "n": len(x), "slope": sl,
                     "r_squared": r ** 2, "p": p})
    return pd.DataFrame(rows)


def direction_vs_volatility(bars: pd.DataFrame, k: int = 16) -> pd.DataFrame:
    """Side-by-side: predicting sign vs predicting magnitude, same horizon."""
    atr = bars["atr14"]
    fwd = (bars["close"].shift(-k) - bars["close"]) / atr
    ok = fwd.notna() & atr.notna() & (atr > 0)
    f = fwd[ok].to_numpy()[::k]
    a = atr[ok].to_numpy()[::k]
    fut_a = atr.shift(-k)[ok].to_numpy()[::k]

    m = np.isfinite(f) & np.isfinite(a) & np.isfinite(fut_a)
    f, a, fut_a = f[m], a[m], fut_a[m]

    _, _, r_dir, p_dir, _ = stats.linregress(np.log(a), f)          # sign
    _, _, r_mag, p_mag, _ = stats.linregress(np.log(a), np.log(fut_a))  # magnitude
    return pd.DataFrame([
        {"target": "direction (signed fwd return)", "n": len(f),
         "r_squared": r_dir ** 2, "p": p_dir},
        {"target": "magnitude (future ATR)", "n": len(f),
         "r_squared": r_mag ** 2, "p": p_mag},
    ])


# ---------------------------------------------------------------------------
# 2. MFE / MAE path structure
# ---------------------------------------------------------------------------
def excursions(minutes: pd.DataFrame, entries: np.ndarray, sides: np.ndarray,
               atr_at_entry: np.ndarray, hold_bars: int) -> pd.DataFrame:
    """Max favourable / adverse excursion in R units for each entry.

    R is defined here as 1 ATR at entry, so excursions are comparable across
    volatility regimes. Also records *when* the favourable peak occurred, which
    is what decides whether a ladder should ratchet early or late.
    """
    hi = minutes["high"].to_numpy()
    lo = minutes["low"].to_numpy()
    cl = minutes["close"].to_numpy()
    n = len(hi)

    rows = []
    for e, side, a in zip(entries, sides, atr_at_entry):
        if not np.isfinite(a) or a <= 0 or e + 1 >= n:
            continue
        end = min(e + hold_bars, n - 1)
        if end <= e:
            continue
        entry_px = cl[e]
        seg_hi, seg_lo = hi[e + 1:end + 1], lo[e + 1:end + 1]
        if len(seg_hi) == 0:
            continue

        if side > 0:
            fav = (np.maximum.accumulate(seg_hi) - entry_px) / a
            adv = (entry_px - np.minimum.accumulate(seg_lo)) / a
        else:
            fav = (entry_px - np.minimum.accumulate(seg_lo)) / a
            adv = (np.maximum.accumulate(seg_hi) - entry_px) / a

        mfe, mae = fav[-1], adv[-1]
        peak_at = int(np.argmax(fav)) + 1
        final = ((cl[end] - entry_px) * side) / a
        rows.append({"mfe_r": mfe, "mae_r": mae, "peak_bar": peak_at,
                     "final_r": final, "hold": end - e})
    return pd.DataFrame(rows)


def random_entry_paths(minutes: pd.DataFrame, bars: pd.DataFrame,
                       n_samples: int = 4000, hold_bars: int = 240,
                       seed: int = 3) -> pd.DataFrame:
    """Excursion profile for entries taken at random times, both directions.

    This is the baseline the ladder must beat: it isolates what the market's
    path structure gives you when the entry carries no information at all.
    """
    rng = np.random.default_rng(seed)
    m_ts = minutes["ts"].to_numpy()
    b = bars.dropna(subset=["atr14"])
    b = b[b["atr14"] > 0]
    if len(b) < 100:
        return pd.DataFrame()

    pick = rng.choice(len(b), size=min(n_samples, len(b)), replace=False)
    chosen = b.iloc[np.sort(pick)]
    idx = np.searchsorted(m_ts, chosen["ts"].to_numpy(), side="right")
    sides = rng.choice([-1, 1], size=len(idx))
    return excursions(minutes, idx, sides, chosen["atr14"].to_numpy(), hold_bars)


def summarise_paths(df: pd.DataFrame, label: str) -> dict:
    if df is None or len(df) == 0:
        return {}
    return {
        "set": label,
        "n": len(df),
        "median_mfe_r": df["mfe_r"].median(),
        "median_mae_r": df["mae_r"].median(),
        "p75_mfe_r": df["mfe_r"].quantile(0.75),
        "p90_mfe_r": df["mfe_r"].quantile(0.90),
        "mfe_over_mae": df["mfe_r"].median() / max(df["mae_r"].median(), 1e-9),
        "median_final_r": df["final_r"].median(),
        "mean_final_r": df["final_r"].mean(),
        "median_peak_bar": df["peak_bar"].median(),
    }


def reach_table(df: pd.DataFrame, levels=(0.5, 1.0, 1.5, 2.0, 3.0, 4.0)) -> pd.DataFrame:
    """How often price reaches each favourable level, and what happens after.

    ``gave_back`` is the share of trades that reached the level and still ended
    below it -- the number a ladder exists to reduce.
    """
    rows = []
    for lv in levels:
        hit = df["mfe_r"] >= lv
        if hit.sum() == 0:
            continue
        after = df.loc[hit]
        rows.append({
            "level_R": lv,
            "reached_pct": hit.mean() * 100,
            "n": int(hit.sum()),
            "median_final_r": after["final_r"].median(),
            "gave_back_pct": (after["final_r"] < lv).mean() * 100,
            "ended_negative_pct": (after["final_r"] < 0).mean() * 100,
        })
    return pd.DataFrame(rows)


def main(data_dir: Path, out_dir: Path, tf: str = "15min") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    bars = add_features(resample(minutes, tf))
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min().date()} -> "
          f"{minutes.index.max().date()}   tf={tf}\n")

    print("=== 1. IS VOLATILITY PREDICTABLE? (direction was not) ===")
    vp = volatility_predictability(bars)
    print(vp.to_string(index=False, float_format=lambda x: f"{x:10.4f}"))
    vp.to_csv(out_dir / "vol_predictability.csv", index=False)

    print("\n=== 2. PREDICTING SIGN vs PREDICTING SIZE, SAME HORIZON ===")
    dv = direction_vs_volatility(bars)
    print(dv.to_string(index=False, float_format=lambda x: f"{x:10.6f}"))

    print("\n=== 3. PATH SHAPE FROM RANDOM ENTRIES (the ladder's baseline) ===")
    paths = random_entry_paths(minutes, bars, n_samples=4000, hold_bars=240)
    s = summarise_paths(paths, "random entries")
    for k, v in s.items():
        print(f"  {k:<20} {v if isinstance(v, (int, str)) else f'{v:.3f}'}")
    paths.to_csv(out_dir / "path_random.csv", index=False)

    print("\n=== 4. HOW OFTEN PRICE REACHES EACH LEVEL, AND WHAT IT GIVES BACK ===")
    rt = reach_table(paths)
    print(rt.to_string(index=False, float_format=lambda x: f"{x:9.2f}"))
    rt.to_csv(out_dir / "path_reach.csv", index=False)
    print("\n  'gave_back_pct' is the share that touched the level and finished")
    print("  below it. That column is the entire case for a ladder: it is the")
    print("  profit that exists on the chart and is not captured by holding.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--tf", default="15min")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out), a.tf)
