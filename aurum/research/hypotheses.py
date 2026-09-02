"""Screen every hypothesis honestly.

Protocol
--------
1. Split the history into TRAIN (first 60%) and TEST (last 40%).  TEST is not
   looked at until the end and is never used to choose anything.
2. For each hypothesis, sweep a small grid on TRAIN and keep the best config.
3. Evaluate that single config on TEST.
4. Report both, plus a p-value and the number of configurations tried, so the
   multiple-testing burden is visible rather than buried.

The number that matters is the TEST column.  A hypothesis that is strong on
TRAIN and absent on TEST has been fitted, not discovered.
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
from ..engine.metrics import bootstrap_pvalue, format_summary, summarise
from ..strategies import library as lib
from ..strategies.base import RiskSpec


def _spec(stop_atr: float, target_r: float, min_stop: float, hold_h: float = 6.0) -> RiskSpec:
    return RiskSpec(stop_atr=stop_atr, target_r=target_r, min_stop_px=min_stop,
                    max_stop_px=25.0, max_hold_h=hold_h)


def grid(**kwargs):
    keys = list(kwargs)
    for combo in itertools.product(*(kwargs[k] for k in keys)):
        yield dict(zip(keys, combo))


# Each entry: name -> (signal builder, parameter grid)
def build_hypotheses(tf: str):
    common_risk = dict(
        stop_atr=[1.0, 1.5, 2.0],
        target_r=[1.5, 2.0, 3.0],
        min_stop=[2.0, 4.0],
    )

    def orb(bars, p):
        return lib.opening_range_breakout(
            bars, _spec(p["stop_atr"], p["target_r"], p["min_stop"]),
            open_min=p["open_min"], range_min=p["range_min"],
            window_min=p.get("window_min", 240),
        )

    def asia(bars, p):
        return lib.asian_range_break(
            bars, _spec(p["stop_atr"], p["target_r"], p["min_stop"]),
        )

    def pull(bars, p):
        return lib.trend_pullback(
            bars, _spec(p["stop_atr"], p["target_r"], p["min_stop"]),
            trade_start=p["trade_start"], trade_end=p["trade_end"],
        )

    def expan(bars, p):
        return lib.volatility_expansion(
            bars, _spec(p["stop_atr"], p["target_r"], p["min_stop"]),
            expansion=p["expansion"],
            trade_start=p["trade_start"], trade_end=p["trade_end"],
        )

    def fade(bars, p):
        return lib.stretch_fade(
            bars, _spec(p["stop_atr"], p["target_r"], p["min_stop"]),
            stretch_atr=p["stretch_atr"],
            trade_start=p["trade_start"], trade_end=p["trade_end"],
        )

    def zone(bars, p):
        return lib.reaction_zone_retest(
            bars, _spec(p["stop_atr"], p["target_r"], p["min_stop"]),
            min_touches=p["min_touches"], cluster_atr=p["cluster_atr"],
            trade_start=p["trade_start"], trade_end=p["trade_end"],
        )

    def sweep(bars, p):
        return lib.sweep_reversal(
            bars, _spec(p["stop_atr"], p["target_r"], p["min_stop"]),
            lookback=p["lookback"], min_poke_atr=p["min_poke"],
            trade_start=p["trade_start"], trade_end=p["trade_end"],
        )

    def vwrev(bars, p):
        return lib.vwap_reversion(
            bars, _spec(p["stop_atr"], p["target_r"], p["min_stop"]),
            stretch=p["stretch"],
            trade_start=p["trade_start"], trade_end=p["trade_end"],
        )

    def imom(bars, p):
        return lib.intraday_momentum(
            bars, _spec(p["stop_atr"], p["target_r"], p["min_stop"], hold_h=8.0),
            anchor_min=p["anchor_min"], signal_min=p["signal_min"],
        )

    hours = dict(trade_start=[7 * 60, 12 * 60], trade_end=[20 * 60])

    return {
        "ORB_London": (orb, list(grid(open_min=[7 * 60], range_min=[30, 60], **common_risk))),
        "ORB_NY":     (orb, list(grid(open_min=[13 * 60, 13 * 60 + 30], range_min=[30, 60], **common_risk))),
        "AsiaBreak":  (asia, list(grid(**common_risk))),
        "Pullback":   (pull, list(grid(**common_risk, **hours))),
        "Expansion":  (expan, list(grid(expansion=[1.5, 2.0], **common_risk, **hours))),
        "Fade":       (fade, list(grid(stretch_atr=[1.5, 2.5], **common_risk, **hours))),
        "Zone":       (zone, list(grid(min_touches=[2, 3], cluster_atr=[0.25], **common_risk, **hours))),
        "SweepRev":   (sweep, list(grid(lookback=[12, 24], min_poke=[0.1, 0.25],
                                        **common_risk, **hours))),
        "VWAPRev":    (vwrev, list(grid(stretch=[1.5, 2.0, 2.5], **common_risk, **hours))),
        "IntradayMom": (imom, list(grid(anchor_min=[13 * 60], signal_min=[16 * 60, 17 * 60],
                                        **common_risk))),
    }


def screen(minutes: pd.DataFrame, tf: str, cost, out_dir: Path,
           train_frac: float = 0.6, min_trades: int = 60) -> pd.DataFrame:
    bars = add_features(resample(minutes, tf))
    split_at = bars.index[int(len(bars) * train_frac)]
    train = bars[bars.index < split_at]
    test = bars[bars.index >= split_at]
    print(f"\n### timeframe {tf}   train {train.index.min().date()}..{train.index.max().date()}"
          f"   test {test.index.min().date()}..{test.index.max().date()}")

    rows = []
    for name, (fn, params) in build_hypotheses(tf).items():
        best, best_s, best_p = None, -np.inf, None
        for p in params:
            sigs = fn(train, p)
            if len(sigs) < min_trades:
                continue
            res = bt_run(minutes, sigs, cost)
            if len(res.trades) < min_trades:
                continue
            s = summarise(res.trades, name)
            if s["expectancy_r"] > best_s:
                best, best_s, best_p = res.trades, s["expectancy_r"], p

        if best is None:
            rows.append({"hypothesis": name, "tf": tf, "status": "too few trades"})
            print(f"  {name:<14} -- insufficient trades on train")
            continue

        tr_s = summarise(best, f"{name} TRAIN")
        te_sigs = fn(test, best_p)
        te_res = bt_run(minutes, te_sigs, cost)
        te_s = summarise(te_res.trades, f"{name} TEST") if len(te_res.trades) else {"n": 0}

        rows.append(
            {
                "hypothesis": name, "tf": tf, "status": "ok",
                "configs_tried": len(params),
                "train_n": tr_s["n"], "train_E_R": round(tr_s["expectancy_r"], 4),
                "train_t": round(tr_s["t_stat"], 2),
                "test_n": te_s.get("n", 0),
                "test_E_R": round(te_s.get("expectancy_r", np.nan), 4) if te_s.get("n") else np.nan,
                "test_t": round(te_s.get("t_stat", np.nan), 2) if te_s.get("n") else np.nan,
                "test_total_R": round(te_s.get("total_r", np.nan), 1) if te_s.get("n") else np.nan,
                "test_win": round(te_s.get("win_rate", np.nan), 3) if te_s.get("n") else np.nan,
                "test_tr_per_day": round(te_s.get("trades_per_trading_day", np.nan), 2) if te_s.get("n") else np.nan,
                "test_p": round(bootstrap_pvalue(te_res.trades["r"].to_numpy()), 4) if te_s.get("n", 0) > 5 else np.nan,
                "best_params": json.dumps(best_p),
            }
        )
        print(f"  {name:<14} train E[R]={tr_s['expectancy_r']:+.4f} (n={tr_s['n']:>4})"
              f"   ->   TEST E[R]={te_s.get('expectancy_r', float('nan')):+.4f} "
              f"(n={te_s.get('n',0):>4}, t={te_s.get('t_stat', float('nan')):+.2f})")

    return pd.DataFrame(rows)


def main(data_dir: Path, out_dir: Path, tfs=("15min", "30min")) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min()} -> {minutes.index.max()}")

    all_rows = []
    for tf in tfs:
        df = screen(minutes, tf, cost_presets.REALISTIC, out_dir)
        all_rows.append(df)

    out = pd.concat(all_rows, ignore_index=True)
    out.to_csv(out_dir / "hypothesis_screen.csv", index=False)
    print(f"\nwrote {out_dir / 'hypothesis_screen.csv'}")

    ok = out[out.status == "ok"].copy()
    if len(ok):
        print("\n=== SURVIVORS (positive out-of-sample expectancy) ===")
        surv = ok[(ok.test_E_R > 0) & (ok.test_n >= 30)].sort_values("test_E_R", ascending=False)
        print(surv[["hypothesis", "tf", "train_E_R", "test_n", "test_E_R",
                    "test_t", "test_p", "test_tr_per_day"]].to_string(index=False)
              if len(surv) else "  none")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--tfs", default="15min,30min")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out), tuple(a.tfs.split(",")))
