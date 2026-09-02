"""What would have to be true for this to work?

Rather than reporting a single pass/fail, this inverts the question:

* **Breakeven cost** - how cheap would execution have to be for expectancy to
  reach zero?  Compare that against what your broker actually charges.  This is
  the most actionable number in the study, because spread is the one input a
  trader can change by moving accounts.
* **Breakeven edge** - how much gross edge would the signal need at *current*
  costs?  Compare against the ~0.06 R that the best mechanism actually shows.
* **Benchmark** - what did simply holding gold return over the same window?
  A bot that underperforms buy-and-hold at higher risk is not worth running,
  and gold's 2022-2026 run makes this a demanding comparison.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes
from ..engine import costs as cost_presets
from ..engine.backtest import run as bt_run
from ..engine.costs import CostModel
from ..engine.metrics import summarise
from ..strategies import library as lib
from ..strategies.base import RiskSpec


def breakeven_cost(minutes: pd.DataFrame, sigs, lo: float = 0.0, hi: float = 4.0,
                   tol: float = 0.01) -> tuple[float, float]:
    """Bisect on the spread markup that drives expectancy to zero.

    Returns (markup, implied round-trip cost in dollars).
    """
    med = float(minutes["spread_med"].median())

    def er(markup: float) -> float:
        c = CostModel(spread_markup=markup, min_spread=0.0,
                      stop_slippage=0.05, entry_slippage=0.02)
        t = bt_run(minutes, sigs, c).raw_trades
        return t["r"].mean() if len(t) else np.nan

    if er(lo) <= 0:
        return (np.nan, np.nan)      # no edge even at zero spread
    if er(hi) > 0:
        return (hi, hi * med + 0.07)  # profitable even at absurd costs

    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if er(mid) > 0:
            lo = mid
        else:
            hi = mid
    mk = (lo + hi) / 2.0
    return (mk, mk * med + 0.07)


def buy_and_hold(minutes: pd.DataFrame) -> dict:
    """Benchmark: hold one ounce for the whole window."""
    px = minutes["close"]
    total = float(px.iloc[-1] - px.iloc[0])
    days = max((px.index[-1] - px.index[0]).days, 1)
    daily = px.resample("1D").last().dropna()
    rets = daily.pct_change().dropna()
    dd = (daily / daily.cummax() - 1).min()
    return {
        "start_px": float(px.iloc[0]),
        "end_px": float(px.iloc[-1]),
        "total_$": total,
        "pct": total / float(px.iloc[0]) * 100,
        "ann_pct": ((float(px.iloc[-1]) / float(px.iloc[0])) ** (365 / days) - 1) * 100,
        "ann_vol_pct": float(rets.std() * np.sqrt(252) * 100),
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else np.nan,
        "max_dd_pct": float(dd * 100),
        "days": days,
    }


def main(data_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    minutes = load_minutes(data_dir)
    med = float(minutes["spread_med"].median())
    print(f"loaded {len(minutes):,} 1m bars  {minutes.index.min().date()} -> "
          f"{minutes.index.max().date()}")
    print(f"median observed spread (Dukascopy ECN): ${med:.3f}\n")

    bh = buy_and_hold(minutes)
    print("=== BENCHMARK: buy and hold gold ===")
    print(f"  {bh['start_px']:.0f} -> {bh['end_px']:.0f}   "
          f"{bh['pct']:+.1f}% total, {bh['ann_pct']:+.1f}%/yr")
    print(f"  ann vol {bh['ann_vol_pct']:.1f}%   Sharpe {bh['sharpe']:.2f}   "
          f"max DD {bh['max_dd_pct']:.1f}%")

    bars15 = add_features(resample(minutes, "15min"))
    print("\n=== BREAKEVEN ANALYSIS PER MECHANISM ===")
    print(f"{'mechanism':<14}{'n':>6}{'gross E[R]':>12}{'net@REAL':>10}"
          f"{'BE markup':>11}{'BE cost $':>11}{'verdict':>26}")
    print("-" * 92)

    specs = RiskSpec(stop_atr=2.5, target_r=2.0, min_stop_px=8.0,
                     max_stop_px=40.0, max_hold_h=12.0)
    mechanisms = {
        "pullback": lambda: lib.trend_pullback(bars15, specs, trade_start=7 * 60, trade_end=20 * 60),
        "pullback 12-16": lambda: lib.trend_pullback(bars15, specs, trade_start=12 * 60, trade_end=16 * 60),
        "fade": lambda: lib.stretch_fade(bars15, specs, trade_start=7 * 60, trade_end=20 * 60),
        "expansion": lambda: lib.volatility_expansion(bars15, specs, trade_start=7 * 60, trade_end=20 * 60),
        "sweep": lambda: lib.sweep_reversal(bars15, specs, trade_start=7 * 60, trade_end=20 * 60),
        "zone": lambda: lib.reaction_zone_retest(bars15, specs, trade_start=7 * 60, trade_end=20 * 60),
    }
    zero = CostModel(spread_markup=0.0, min_spread=0.0, stop_slippage=0.0, entry_slippage=0.0)

    rows = []
    for name, fn in mechanisms.items():
        sigs = fn()
        if len(sigs) < 50:
            continue
        g = bt_run(minutes, sigs, zero).raw_trades
        n_ = bt_run(minutes, sigs, cost_presets.REALISTIC).raw_trades
        if len(g) < 50:
            continue
        gross, net = g["r"].mean(), n_["r"].mean()
        mk, becost = breakeven_cost(minutes, sigs)

        if not np.isfinite(mk):
            verdict = "no edge at ANY cost"
        elif becost < 0.20:
            verdict = "needs sub-institutional cost"
        elif becost < 0.45:
            verdict = "needs a top-tier ECN"
        else:
            verdict = "viable at retail cost"
        rows.append({"mechanism": name, "n": len(g), "gross_E_R": round(gross, 4),
                     "net_E_R": round(net, 4), "be_markup": round(mk, 2) if np.isfinite(mk) else None,
                     "be_cost_usd": round(becost, 3) if np.isfinite(becost) else None,
                     "verdict": verdict})
        print(f"{name:<14}{len(g):>6}{gross:>+12.4f}{net:>+10.4f}"
              f"{(f'{mk:.2f}x' if np.isfinite(mk) else '-'):>11}"
              f"{(f'${becost:.3f}' if np.isfinite(becost) else '-'):>11}{verdict:>26}")

    pd.DataFrame(rows).to_csv(out_dir / "breakeven.csv", index=False)
    print(f"\nFor reference, a realistic retail round trip on gold is $0.45-$1.20 "
          f"(spread + slippage).\nAny mechanism whose breakeven cost sits below that "
          f"cannot be traded profitably by a retail account.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bars")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    main(Path(a.data), Path(a.out))
