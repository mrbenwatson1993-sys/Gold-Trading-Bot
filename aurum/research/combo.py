"""Assemble the final bot: several entries, one regime filter, one exit.

The grid settled the design questions individually. Long-only beat both sides at
every timeframe. A 4-hour or daily trend filter beat a 1-hour one or none. Wide
exits (ATR trail, ladder, 3R) beat tight ones, and a fixed 1R target was worst of
all. The 1-hour decision bar dominated the top of the table.

What the grid could not answer is the question that actually matters for a
deployable bot: **how many trades a day can you get without diluting the edge?**
A single entry on 1-hour bars fires a few times a week. Five entries that fire at
genuinely different moments fire far more often -- but only if they are not just
five descriptions of the same trade.

So this module does three things:

1. measures how much the entries actually **overlap**, so "more entries" is not
   confused with "more trades";
2. sweeps entry subsets for the frequency/expectancy frontier;
3. walk-forwards the chosen combination, picking the exit in-sample per fold and
   trading it out-of-sample, so the reported numbers are not the ones that were
   fitted.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes
from ..engine import costs as cost_presets
from ..engine.backtest import MARKET, Ladder, Signal, apply_caps, resolve
from ..engine.metrics import bootstrap_pvalue, deflated_sharpe, summarise
from ..engine.walkforward import make_folds
from .grid import ENTRIES, htf_bias

EXITS = {
    "trail_4atr": Ladder(trail_atr=4.0),
    "ladder_1.5/3/5": Ladder(steps=((1.5, 0.0), (3.0, 1.5), (5.0, 3.2))),
    "fixed_3R": Ladder(target_r=3.0),
    "BE@1R_tp3R": Ladder(steps=((1.0, 0.0),), target_r=3.0),
    "ladder_1/2/3": Ladder(steps=((1.0, 0.0), (2.0, 0.8), (3.0, 1.8))),
}


def entry_signals(bars, bias, names, stop_atr=2.0, min_stop=10.0,
                  hold_h=72, lad=None, long_only=True) -> list[Signal]:
    """Union of the named entry families, long-only, gated by the HTF trend."""
    out: list[Signal] = []
    seen: set[int] = set()
    for nm in names:
        L, S, _ = ENTRIES[nm](bars)
        if long_only:
            S = pd.Series(False, index=bars.index)
        if bias is not None:
            L = L & (bias >= 1)
            S = S & (bias <= -1)
        for mask, side in ((L, 1), (S, -1)):
            sub = bars[mask.fillna(False)]
            for _, bar in sub.iterrows():
                atr = float(bar["atr14"])
                if not np.isfinite(atr) or atr <= 0:
                    continue
                ts = int(bar["ts"])
                key = ts * 2 + (0 if side > 0 else 1)
                if key in seen:            # same bar, same side, two triggers
                    continue
                seen.add(key)
                dist = float(np.clip(atr * stop_atr, min_stop, 200.0))
                px = float(bar["close"])
                out.append(Signal(
                    ts=ts, side=side, entry_px=px,
                    stop_px=px - dist * side, target_px=px + dist * 99 * side,
                    entry_type=MARKET, max_hold_ms=int(hold_h * 3600_000),
                    atr=atr, ladder=lad, tag=nm,
                ))
    return sorted(out, key=lambda s: s.ts)


def overlap_matrix(bars, bias, names) -> pd.DataFrame:
    """Share of bars on which each pair of entries fires together.

    High overlap means two 'different' entries are the same trade wearing a
    different name, and combining them buys frequency that is not really there.
    """
    masks = {}
    for nm in names:
        L, _, _ = ENTRIES[nm](bars)
        if bias is not None:
            L = L & (bias >= 1)
        masks[nm] = L.fillna(False)
    out = pd.DataFrame(index=names, columns=names, dtype=float)
    for a, b in itertools.product(names, names):
        ma, mb = masks[a], masks[b]
        denom = (ma | mb).sum()
        out.loc[a, b] = round((ma & mb).sum() / denom * 100, 1) if denom else np.nan
    return out


def evaluate(path, bars, bias, names, lad, cost, max_conc, **kw) -> dict | None:
    sigs = entry_signals(bars, bias, names, lad=lad, **kw)
    if len(sigs) < 60:
        return None
    raw, _, _ = resolve(path, sigs, cost)
    if len(raw) < 60:
        return None
    t = apply_caps(raw, max_concurrent=max_conc, max_daily_loss_r=4.0)
    if len(t) < 60:
        return None
    s = summarise(t)
    return {"n": s["n"], "E_R": round(s["expectancy_r"], 4),
            "tr_day": round(s["trades_per_available_day"], 2),
            "win": round(s["win_rate"], 3), "PF": round(s["profit_factor"], 2),
            "totR": round(s["total_r"], 1), "maxDD": round(s["max_dd_r"], 1),
            "t": round(s["t_stat"], 2),
            "p": round(bootstrap_pvalue(t["r"].to_numpy()), 4),
            "trades": t}


def walk_forward(minutes, tf_rule="60min", path_rule="15min", htf="4h",
                 names=("pullback_ema20",), cost=cost_presets.REALISTIC,
                 max_conc=3, stop_atr=2.0, min_stop=10.0, hold_h=72):
    """Choose the exit in-sample per fold; trade it out-of-sample."""
    bars = add_features(resample(minutes, tf_rule))
    path = resample(minutes, path_rule)
    bias = htf_bias(minutes, {"1h": "60min", "4h": "240min", "1D": "1D"}[htf],
                    bars.index) if htf != "none" else None
    folds = make_folds(bars.index, 12, 3, 3)

    oos, chosen = [], []
    for fo in folds:
        tr = bars[(bars.index >= fo.train_start) & (bars.index < fo.train_end)]
        te = bars[(bars.index >= fo.test_start) & (bars.index < fo.test_end)]
        if len(tr) < 400 or len(te) < 100:
            continue
        btr = bias.reindex(tr.index) if bias is not None else None
        bte = bias.reindex(te.index) if bias is not None else None

        best, best_e = None, -np.inf
        for xn, lad in EXITS.items():
            r = evaluate(path, tr, btr, names, lad, cost, max_conc,
                         stop_atr=stop_atr, min_stop=min_stop, hold_h=hold_h)
            if r and r["E_R"] > best_e:
                best, best_e = (xn, lad), r["E_R"]
        if best is None:
            continue
        r = evaluate(path, te, bte, names, best[1], cost, max_conc,
                     stop_atr=stop_atr, min_stop=min_stop, hold_h=hold_h)
        if r:
            t = r["trades"].copy()
            t["fold"] = fo.test_start
            oos.append(t)
        chosen.append({"test_start": fo.test_start.date(), "exit": best[0],
                       "train_E_R": round(best_e, 4)})
    return (pd.concat(oos, ignore_index=True) if oos else pd.DataFrame()), pd.DataFrame(chosen)


def report(oos, chosen, label, n_cfg):
    if oos is None or len(oos) == 0:
        print(f"{label}: no out-of-sample trades")
        return None
    s = summarise(oos)
    p = bootstrap_pvalue(oos["r"].to_numpy())
    dsr = deflated_sharpe(s["sharpe"], s["n"], max(n_cfg * max(len(chosen), 1), 1))
    print(f"\n=== {label} — OUT OF SAMPLE ONLY ===")
    print(f"  n={s['n']}  trades/day={s['trades_per_available_day']:.2f}  "
          f"E[R]={s['expectancy_r']:+.4f}  total={s['total_r']:+.1f}R")
    print(f"  win={s['win_rate']:.1%}  PF={s['profit_factor']:.2f}  "
          f"maxDD={s['max_dd_r']:.1f}R  t={s['t_stat']:+.2f}  p={p:.4f}  "
          f"deflated Sharpe P(SR>0)={dsr:.3f}")
    if len(chosen):
        print(f"  exit chosen per fold: "
              f"{dict(chosen['exit'].value_counts())}")
    return {"n": s["n"], "E_R": s["expectancy_r"], "tr_day": s["trades_per_available_day"],
            "totR": s["total_r"], "maxDD": s["max_dd_r"], "t": s["t_stat"],
            "p": p, "dsr": dsr}
