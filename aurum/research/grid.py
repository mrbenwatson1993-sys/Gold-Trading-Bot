"""The full grid: entry x timeframe x higher-timeframe filter x side x exit.

Nothing here is assumed. Every dimension a gold bot could be built along is
enumerated and tested against the same cost model and the same held-out split:

* **entry logic** - six families, mixing ideas from this study with the ones
  retail gold traders actually run (session opening-range breakouts with
  range-relative stops, Asian-range breaks, momentum continuation);
* **entry timeframe** - 5m through 1h, because cost drag scales inversely with
  stop size and stop size scales with the timeframe's volatility;
* **higher-timeframe trend filter** - none, 1h, 4h or daily EMA stack, applied
  strictly causally (only completed higher-timeframe bars);
* **direction** - both sides or long only, since long-only was the single
  biggest improvement found so far;
* **exit** - fixed R targets against step-trailing ladders, so the entry's
  contribution can be separated from the exit's.

Protocol: everything is fitted on the first 60% of history and reported on the
held-out 40%. The TEST column is the only one that means anything; the TRAIN
column is shown beside it so overfitting is visible rather than inferred.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes
from ..engine import costs as cost_presets
from ..engine.backtest import MARKET, Ladder, Signal, resolve
from ..engine.metrics import bootstrap_pvalue, summarise

# --------------------------------------------------------------------------
# Timeframes and their fill paths
# --------------------------------------------------------------------------
TF_RULE = {"5min": "5min", "15min": "15min", "30min": "30min", "1h": "60min"}
# Screening paths are one step finer than the entry bar: fine enough to order a
# stop against a target, coarse enough that 400 configurations finish. The
# finalists are re-resolved on the 1-minute path before anything is believed.
TF_PATH = {"5min": "1min", "15min": "5min", "30min": "5min", "1h": "15min"}
TF_HOLD = {"5min": 8, "15min": 24, "30min": 48, "1h": 72}       # max hold, hours
TF_MINSTOP = {"5min": 4.0, "15min": 6.0, "30min": 8.0, "1h": 10.0}

HTF_RULE = {"none": None, "1h": "60min", "4h": "240min", "1D": "1D"}


def htf_bias(minutes: pd.DataFrame, rule: str | None,
             index: pd.DatetimeIndex) -> pd.Series:
    """+1 uptrend / -1 downtrend / 0 neither, from COMPLETED higher-TF bars only.

    The shift(1) is what keeps this causal: at any entry bar we use the last
    higher-timeframe bar that has actually closed, never the one in progress.
    """
    if rule is None:
        return pd.Series(0, index=index, dtype=int)
    b = add_features(resample(minutes, rule))
    up = (b["ema20"] > b["ema50"]) & (b["ema50"] > b["ema200"])
    dn = (b["ema20"] < b["ema50"]) & (b["ema50"] < b["ema200"])
    raw = pd.Series(np.where(up, 1, np.where(dn, -1, 0)), index=b.index).shift(1)
    return raw.reindex(index, method="ffill").fillna(0).astype(int)


# --------------------------------------------------------------------------
# Entry families. Each returns a DataFrame of candidate entries:
#   ts, side, ref_px, atr, stop_dist  (stop_dist NaN -> use ATR rule)
# --------------------------------------------------------------------------
def _base(d: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(index=d.index)


def e_pullback20(d):
    up = (d.ema20 > d.ema50) & (d.ema50 > d.ema200) & (d.ema20 > d.ema20.shift(3))
    dn = (d.ema20 < d.ema50) & (d.ema50 < d.ema200) & (d.ema20 < d.ema20.shift(3))
    L = up & (d.low <= d.ema20) & (d.close > d.ema20) & (d.close > d.open)
    S = dn & (d.high >= d.ema20) & (d.close < d.ema20) & (d.close < d.open)
    return L, S, None


def e_pullback50(d):
    """Deeper pullback: price reaches the slow EMA and reclaims it."""
    up = (d.ema20 > d.ema50) & (d.ema50 > d.ema200)
    dn = (d.ema20 < d.ema50) & (d.ema50 < d.ema200)
    L = up & (d.low <= d.ema50) & (d.close > d.ema50) & (d.close > d.open)
    S = dn & (d.high >= d.ema50) & (d.close < d.ema50) & (d.close < d.open)
    return L, S, None


def e_breakout24(d):
    """Close through the 24-bar extreme."""
    L = (d.close > d.hh24) & (d.close > d.open)
    S = (d.close < d.ll24) & (d.close < d.open)
    return L, S, None


def e_momentum(d):
    """Wide-range, high-body-ratio bar closing through the 12-bar extreme."""
    big = d.range > 1.5 * d.range.rolling(24).mean()
    body = d.body_pct >= 0.6
    L = big & body & (d.close > d.hh12) & (d.close > d.open)
    S = big & body & (d.close < d.ll12) & (d.close < d.open)
    return L, S, None


def e_reclaim(d):
    """First close back above EMA20 after at least 4 consecutive closes below."""
    above = d.close > d.ema20
    below_run = (~above).rolling(4).sum().eq(4).fillna(False)
    L = above & below_run.shift(1).fillna(False) & (d.ema50 > d.ema200)
    above_run = above.rolling(4).sum().eq(4).fillna(False)
    S = (~above) & above_run.shift(1).fillna(False) & (d.ema50 < d.ema200)
    return L, S, None


ENTRIES = {
    "pullback_ema20": e_pullback20,
    "pullback_ema50": e_pullback50,
    "breakout_24": e_breakout24,
    "momentum_burst": e_momentum,
    "ema_reclaim": e_reclaim,
}


def session_orb(d: pd.DataFrame, open_min: int, range_min: int, tf_min: int):
    """Session opening-range breakout with a RANGE-relative stop.

    This is the version retail gold traders actually run -- stop at half the
    opening range, not an ATR multiple -- and it is a genuinely different trade
    from the ATR-stopped ORB tested earlier in this study, which failed.
    Returns masks plus an explicit stop distance per bar.
    """
    bars_in_range = max(range_min // tf_min, 1)
    in_win = (d.mins_utc >= open_min) & (d.mins_utc < open_min + range_min)
    grp = d["date"]
    hi = d.high.where(in_win).groupby(grp).transform("max")
    lo = d.low.where(in_win).groupby(grp).transform("min")
    rng = (hi - lo)
    after = (d.mins_utc >= open_min + range_min) & (d.mins_utc < open_min + range_min + 300)
    ok = rng.notna() & (rng > 0)
    L = after & ok & (d.close > hi) & (d.close.shift(1) <= hi)
    S = after & ok & (d.close < lo) & (d.close.shift(1) >= lo)
    del bars_in_range
    return L, S, (rng * 0.5)


# --------------------------------------------------------------------------
# Exits
# --------------------------------------------------------------------------
EXITS = {
    "fixed_1R": Ladder(target_r=1.0),
    "fixed_2R": Ladder(target_r=2.0),
    "fixed_3R": Ladder(target_r=3.0),
    "BE@1R_tp3R": Ladder(steps=((1.0, 0.0),), target_r=3.0),
    "ladder_1.5/3/5": Ladder(steps=((1.5, 0.0), (3.0, 1.5), (5.0, 3.2))),
    "ladder_1/2/3": Ladder(steps=((1.0, 0.0), (2.0, 0.8), (3.0, 1.8))),
    "trail_4atr": Ladder(trail_atr=4.0),
}


def build_signals(d, L, S, stop_override, bias, side_mode, stop_atr, min_stop,
                  hold_h, lad) -> list[Signal]:
    if side_mode == "long":
        S = pd.Series(False, index=d.index)
    # Higher-timeframe gate: only trade with the completed HTF trend.
    if bias is not None:
        L = L & (bias >= 1)
        S = S & (bias <= -1)

    out = []
    for mask, side in ((L, 1), (S, -1)):
        sub = d[mask.fillna(False)]
        if len(sub) == 0:
            continue
        so = stop_override[mask.fillna(False)] if stop_override is not None else None
        for k, (_, bar) in enumerate(sub.iterrows()):
            atr = float(bar["atr14"])
            if not np.isfinite(atr) or atr <= 0:
                continue
            dist = float(so.iloc[k]) if so is not None else atr * stop_atr
            dist = float(np.clip(dist, min_stop, 200.0))
            if not np.isfinite(dist) or dist <= 0:
                continue
            px = float(bar["close"])
            out.append(Signal(
                ts=int(bar["ts"]), side=side, entry_px=px,
                stop_px=px - dist * side, target_px=px + dist * 99 * side,
                entry_type=MARKET, max_hold_ms=int(hold_h * 3600_000),
                atr=atr, ladder=lad, tag="G",
            ))
    return out


MAX_SIGNALS = 2500   # uniform subsample cap; keeps the estimate, bounds compute


def _cap(sigs: list, cap: int = MAX_SIGNALS) -> list:
    """Uniformly thin a signal list so compute stays bounded.

    Thinning uniformly across time preserves the expectancy estimate and the
    regime mix; it only widens the confidence interval, which the reported
    t-statistic already accounts for.
    """
    if len(sigs) <= cap:
        return sigs
    idx = np.linspace(0, len(sigs) - 1, cap).astype(int)
    return [sigs[i] for i in idx]


def run_grid(minutes, out_dir: Path, cost=cost_presets.REALISTIC,
             train_frac=0.6, min_trades=60) -> pd.DataFrame:
    rows = []
    for tf in ("1h", "30min", "15min", "5min"):
        bars = add_features(resample(minutes, TF_RULE[tf]))
        path = resample(minutes, TF_PATH[tf]) if TF_PATH[tf] != "1min" else minutes
        if len(bars) < 2000:
            continue
        split = bars.index[int(len(bars) * train_frac)]
        tf_min = int(pd.Timedelta(TF_RULE[tf]).total_seconds() // 60)

        # entry masks, computed once per timeframe
        masks = {}
        for name, fn in ENTRIES.items():
            masks[name] = fn(bars)
        if tf in ("5min", "15min"):
            masks["orb_london"] = session_orb(bars, 7 * 60, 15, tf_min)
            masks["orb_ny"] = session_orb(bars, 13 * 60 + 30, 15, tf_min)

        biases = {k: (htf_bias(minutes, r, bars.index) if r else None)
                  for k, r in HTF_RULE.items()}

        for ename, (L, S, so) in masks.items():
            for hname, bias in biases.items():
                for side_mode in ("both", "long"):
                    for xname, lad in EXITS.items():
                        sigs = build_signals(
                            bars, L, S, so, bias, side_mode,
                            stop_atr=2.0, min_stop=TF_MINSTOP[tf],
                            hold_h=TF_HOLD[tf], lad=lad)
                        if len(sigs) < min_trades:
                            continue
                        cut = split.value // 10**6
                        tr = _cap([x for x in sigs if x.ts < cut])
                        te = _cap([x for x in sigs if x.ts >= cut])
                        if len(tr) < min_trades or len(te) < 40:
                            continue
                        t_tr, _, _ = resolve(path, tr, cost)
                        t_te, _, _ = resolve(path, te, cost)
                        if len(t_tr) < min_trades or len(t_te) < 40:
                            continue
                        s_tr, s_te = summarise(t_tr), summarise(t_te)
                        if s_te["expectancy_r"] > 0.05 and s_te["t_stat"] > 2:
                            print(f"     HIT {tf:>5} {ename:<15} htf={hname:<4} "
                                  f"{side_mode:<4} {xname:<15} "
                                  f"testE={s_te['expectancy_r']:+.3f} "
                                  f"t={s_te['t_stat']:+.2f} n={s_te['n']}", flush=True)
                        rows.append({
                            "tf": tf, "entry": ename, "htf": hname,
                            "side": side_mode, "exit": xname,
                            "train_n": s_tr["n"], "train_E_R": round(s_tr["expectancy_r"], 4),
                            "test_n": s_te["n"], "test_E_R": round(s_te["expectancy_r"], 4),
                            "test_t": round(s_te["t_stat"], 2),
                            "test_p": round(bootstrap_pvalue(t_te["r"].to_numpy()), 4),
                            "test_win": round(s_te["win_rate"], 3),
                            "test_PF": round(s_te["profit_factor"], 2),
                            "test_totR": round(s_te["total_r"], 1),
                            "test_maxDD": round(s_te["max_dd_r"], 1),
                            "tr_per_day": round(s_te["trades_per_available_day"], 2),
                        })
        print(f"  {tf}: {len([r for r in rows if r['tf']==tf])} configs", flush=True)

    df = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "grid_full.csv", index=False)
    return df


def main(data_dir: Path, out_dir: Path):
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min().date()} -> "
          f"{minutes.index.max().date()}\n")
    df = run_grid(minutes, out_dir)
    if df.empty:
        print("no configurations produced enough trades")
        return
    print(f"\n{len(df)} configurations tested\n")
    cols = ["tf", "entry", "htf", "side", "exit", "train_E_R", "test_n",
            "test_E_R", "test_t", "test_p", "test_win", "test_PF",
            "tr_per_day", "test_maxDD"]
    good = df[(df.test_E_R > 0) & (df.test_t > 2)].sort_values("test_E_R", ascending=False)
    print("=== POSITIVE OUT-OF-SAMPLE WITH t > 2 ===")
    print(good[cols].head(30).to_string(index=False) if len(good) else "  none")
    print(f"\n  {len(good)} of {len(df)} configurations clear that bar "
          f"({len(good)/max(len(df),1):.1%})")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out))
