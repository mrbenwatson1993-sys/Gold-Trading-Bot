"""Resample 1-minute bars to a decision timeframe and attach features.

Gold trades roughly Sunday 21:00 UTC to Friday 21:00 UTC.  Resampling must not
invent bars across the weekend gap or across the daily maintenance break, so we
resample and then drop empty periods rather than forward-filling.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def resample(minutes: pd.DataFrame, rule: str) -> pd.DataFrame:
    """1m -> ``rule`` (e.g. "5min", "15min"). Empty periods are dropped."""
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "spread_med": "median",
        "ticks": "sum",
    }
    out = minutes.resample(rule, label="right", closed="left").agg(agg)
    out = out.dropna(subset=["open", "close"])
    out = out[out["ticks"] > 0].copy()
    # Be explicit about the unit: pandas >=3 keeps the index's own resolution,
    # so astype("int64") on a datetime64[ms] index yields milliseconds, not
    # nanoseconds. Converting first makes this correct on any pandas version.
    out["ts"] = out.index.tz_convert("UTC").tz_localize(None).astype("datetime64[ms]").astype("int64")
    return out


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the feature set every strategy draws on.

    Everything here is causal: value at bar *i* uses only bars <= i.  Strategy
    code is responsible for the additional shift when it acts on bar i+1.
    """
    d = df.copy()
    d["atr14"] = atr(d, 14)
    d["atr50"] = atr(d, 50)
    d["atr_ratio"] = d["atr14"] / d["atr50"].replace(0, np.nan)

    d["ema20"] = ema(d["close"], 20)
    d["ema50"] = ema(d["close"], 50)
    d["ema200"] = ema(d["close"], 200)
    d["rsi14"] = rsi(d["close"], 14)

    d["ret1"] = d["close"].pct_change()
    d["range"] = d["high"] - d["low"]
    d["body"] = (d["close"] - d["open"]).abs()
    d["body_pct"] = d["body"] / d["range"].replace(0, np.nan)

    # Realised volatility over the last 12 bars, in price units.
    d["rvol"] = d["ret1"].rolling(12).std() * d["close"]

    # Session clock (UTC). Gold's liquidity regimes are session-driven.
    idx = d.index
    d["hour"] = idx.hour
    d["minute"] = idx.minute
    d["dow"] = idx.dayofweek
    d["date"] = idx.normalize()
    d["mins_utc"] = idx.hour * 60 + idx.minute

    # Rolling structure levels used by breakout/sweep logic.
    for n in (12, 24, 48):
        d[f"hh{n}"] = d["high"].rolling(n).max().shift(1)
        d[f"ll{n}"] = d["low"].rolling(n).min().shift(1)

    return d


def session_stats(minutes: pd.DataFrame) -> pd.DataFrame:
    """Median spread and tick activity by UTC hour - the liquidity map."""
    m = minutes.copy()
    m["hour"] = m.index.hour
    g = m.groupby("hour")
    return pd.DataFrame(
        {
            "median_spread": g["spread_med"].median(),
            "p90_spread": g["spread_med"].quantile(0.90),
            "mean_ticks": g["ticks"].mean(),
            "mean_range": g.apply(
                lambda x: (x["high"] - x["low"]).mean(), include_groups=False
            ),
        }
    )
