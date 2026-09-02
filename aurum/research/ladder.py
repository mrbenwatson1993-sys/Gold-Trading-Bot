"""Design and optimise the step-trailing ("ladder") exit.

This is the honest way to evaluate an exit policy, and it is not how it is
usually done. Exits are normally tuned on top of an entry signal, which makes
the two impossible to separate: a ladder that looks brilliant may simply be
riding a good entry, and one that looks useless may be rescuing a bad one.

So every variant is run twice:

**On random entries.** Coin-flip direction, arbitrary times. The entry carries
zero information by construction, so whatever the ladder produces here is
attributable to the exit alone. This is also a hard control: on a driftless
process with no costs, *every* exit policy must come out at roughly zero
expectancy. Optional stopping guarantees it. Any variant that shows a
meaningful profit here is a bug or a fluke, not a discovery -- and checking
that is the first thing this module does.

**On the best available entry.** Whatever the entry contributes, the *ranking*
of ladder variants tells us which exit shape best converts the path structure
measured in ``pathshape.py`` into realised P&L.

The metric that matters is net expectancy after real costs, but the report also
carries win rate, drawdown and the exit-reason mix, because a ladder's whole
job is to change the *shape* of the return distribution.
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
from ..engine.costs import CostModel
from ..engine.metrics import bootstrap_pvalue, summarise

ZERO = CostModel(spread_markup=0.0, min_spread=0.0,
                 stop_slippage=0.0, entry_slippage=0.0)


# ---------------------------------------------------------------------------
# Variant catalogue
# ---------------------------------------------------------------------------
def variants() -> list[Ladder]:
    """The ladder shapes worth comparing, from crude to adaptive."""
    v: list[Ladder] = []

    # Baselines: fixed targets, no ratchet at all.
    for tp in (1.0, 1.5, 2.0, 3.0):
        v.append(Ladder(target_r=tp))

    # Single rung: breakeven only. The most common retail exit.
    for trig in (0.5, 1.0, 1.5):
        v.append(Ladder(steps=((trig, 0.0),)))

    # Two rungs: breakeven then lock a slice.
    for trig2, lock2 in ((1.5, 0.5), (2.0, 0.5), (2.0, 1.0), (3.0, 1.5)):
        v.append(Ladder(steps=((1.0, 0.0), (trig2, lock2))))

    # Three rungs: a genuine ladder that keeps climbing.
    v.append(Ladder(steps=((1.0, 0.0), (2.0, 0.8), (3.0, 1.8))))
    v.append(Ladder(steps=((0.75, 0.0), (1.5, 0.5), (2.5, 1.3), (4.0, 2.6))))
    v.append(Ladder(steps=((1.0, 0.3), (2.0, 1.1), (3.0, 2.0), (5.0, 3.8))))

    # Continuous give-back: keep a fixed share of the best excursion.
    for gb in (0.30, 0.40, 0.50, 0.60):
        v.append(Ladder(give_back_frac=gb))

    # Volatility-scaled trail. Justified by the measurement that volatility is
    # predictable (R^2 ~ 0.60) while direction is not.
    for ta in (1.5, 2.5, 4.0):
        v.append(Ladder(trail_atr=ta))

    # Hybrid: rungs secure the early move, then an ATR trail runs the tail.
    for ta in (2.0, 3.0):
        v.append(Ladder(steps=((1.0, 0.0), (2.0, 0.8)), trail_atr=ta))
    v.append(Ladder(steps=((1.0, 0.0), (2.0, 1.0)), give_back_frac=0.4))

    # Ladder plus a cap, to see whether letting the tail run pays at all.
    v.append(Ladder(steps=((1.0, 0.0), (2.0, 1.0)), target_r=3.0))
    v.append(Ladder(steps=((1.0, 0.0),), target_r=2.0))
    return v


# ---------------------------------------------------------------------------
# Entry sets
# ---------------------------------------------------------------------------
def random_entries(bars: pd.DataFrame, stop_atr: float, min_stop: float,
                   n: int = 3000, hold_h: float = 24.0, seed: int = 5,
                   ladder: Ladder | None = None) -> list[Signal]:
    """Coin-flip entries: the control that isolates the exit's contribution."""
    rng = np.random.default_rng(seed)
    b = bars.dropna(subset=["atr14"])
    b = b[b["atr14"] > 0]
    if len(b) == 0:
        return []
    pick = np.sort(rng.choice(len(b), size=min(n, len(b)), replace=False))
    out = []
    for i in pick:
        row = b.iloc[i]
        atr = float(row["atr14"])
        dist = float(np.clip(atr * stop_atr, min_stop, 200.0))
        side = int(rng.choice([-1, 1]))
        px = float(row["close"])
        out.append(Signal(
            ts=int(row["ts"]), side=side, entry_px=px,
            stop_px=px - dist * side, target_px=px + dist * 99 * side,
            entry_type=MARKET, max_hold_ms=int(hold_h * 3600_000),
            tag="RANDOM", atr=atr, ladder=ladder,
        ))
    return out


def signal_entries(bars: pd.DataFrame, stop_atr: float, min_stop: float,
                   hold_h: float = 24.0, ladder: Ladder | None = None) -> list[Signal]:
    """Trend-pullback entries -- the best entry the study found."""
    from ..strategies import library as lib
    from ..strategies.base import RiskSpec

    spec = RiskSpec(stop_atr=stop_atr, target_r=99.0, min_stop_px=min_stop,
                    max_stop_px=200.0, max_hold_h=hold_h)
    sigs = lib.trend_pullback(bars, spec, trade_start=0, trade_end=1440)
    for s in sigs:
        s.ladder = ladder
    return sigs


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate(path: pd.DataFrame, bars: pd.DataFrame, lad: Ladder,
             entry: str, cost, stop_atr: float, min_stop: float,
             hold_h: float, n_random: int, seed: int) -> dict | None:
    if entry == "random":
        sigs = random_entries(bars, stop_atr, min_stop, n_random, hold_h, seed, lad)
    else:
        sigs = signal_entries(bars, stop_atr, min_stop, hold_h, lad)
    if len(sigs) < 60:
        return None

    trades, _, _ = resolve(path, sigs, cost)
    if len(trades) < 60:
        return None
    s = summarise(trades)
    reasons = trades["reason"].value_counts(normalize=True)
    return {
        "ladder": lad.name,
        "entry": entry,
        "n": s["n"],
        "E_R": round(s["expectancy_r"], 4),
        "win": round(s["win_rate"], 3),
        "avg_win": round(trades.loc[trades.r > 0, "r"].mean(), 3) if (trades.r > 0).any() else np.nan,
        "avg_loss": round(trades.loc[trades.r <= 0, "r"].mean(), 3) if (trades.r <= 0).any() else np.nan,
        "PF": round(s["profit_factor"], 3),
        "maxDD_R": round(s["max_dd_r"], 1),
        "total_R": round(s["total_r"], 1),
        "t": round(s["t_stat"], 2),
        "hold_h": round(s["avg_hold_min"] / 60, 1),
        "pct_stopped": round(reasons.get("stop", 0.0) * 100, 1),
        "pct_breakeven": round(reasons.get("breakeven", 0.0) * 100, 1),
        "pct_locked": round(sum(v for k, v in reasons.items()
                                if str(k).startswith("ladder_lock")) * 100, 1),
        "pct_target": round(reasons.get("target", 0.0) * 100, 1),
        "pct_timeout": round(reasons.get("timeout", 0.0) * 100, 1),
    }


def sweep(minutes: pd.DataFrame, tf: str, cost, entry: str,
          stop_atr: float = 2.0, min_stop: float = 6.0, hold_h: float = 24.0,
          n_random: int = 3000, seed: int = 5) -> pd.DataFrame:
    bars = add_features(resample(minutes, tf))
    path = resample(minutes, "5min") if tf not in ("1min", "5min") else minutes
    rows = []
    for lad in variants():
        r = evaluate(path, bars, lad, entry, cost, stop_atr, min_stop,
                     hold_h, n_random, seed)
        if r:
            r["tf"] = tf
            rows.append(r)
    return pd.DataFrame(rows)


def control_check(minutes: pd.DataFrame, tf: str = "15min") -> pd.DataFrame:
    """Zero-cost random entries: every ladder must land near zero expectancy.

    This is the falsification test for the whole module. If a ladder shows a
    real profit on coin-flip entries with costs switched off, the engine is
    looking ahead somewhere.
    """
    return sweep(minutes, tf, ZERO, "random").sort_values("E_R", ascending=False)


def main(data_dir: Path, out_dir: Path, tf: str = "15min") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min().date()} -> "
          f"{minutes.index.max().date()}   tf={tf}\n")

    cols = ["ladder", "n", "E_R", "win", "avg_win", "avg_loss", "PF", "maxDD_R",
            "t", "hold_h", "pct_stopped", "pct_breakeven", "pct_locked",
            "pct_target", "pct_timeout"]

    print("=== CONTROL: random entries, ZERO costs ===")
    print("Every row must sit near zero. A clear winner here would mean a bug.\n")
    ctl = control_check(minutes, tf)
    print(ctl[cols].to_string(index=False))
    ctl.to_csv(out_dir / f"ladder_control_{tf}.csv", index=False)
    worst = ctl["E_R"].abs().max()
    print(f"\n  largest |E[R]| across all variants: {worst:.4f}")
    print("  (expected near zero: a driftless path cannot be exited into a profit)")

    print("\n\n=== RANDOM ENTRIES, REALISTIC COSTS ===")
    rnd = sweep(minutes, tf, cost_presets.REALISTIC, "random").sort_values("E_R", ascending=False)
    print(rnd[cols].to_string(index=False))
    rnd.to_csv(out_dir / f"ladder_random_{tf}.csv", index=False)

    print("\n\n=== TREND-PULLBACK ENTRIES, REALISTIC COSTS ===")
    sig = sweep(minutes, tf, cost_presets.REALISTIC, "signal").sort_values("E_R", ascending=False)
    print(sig[cols].to_string(index=False))
    sig.to_csv(out_dir / f"ladder_signal_{tf}.csv", index=False)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--tf", default="15min")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out), a.tf)
