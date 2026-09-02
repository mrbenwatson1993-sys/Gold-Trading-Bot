"""Path-accurate backtest simulator.

Signals are produced on a decision timeframe (5m, 15m, ...) but every fill is
resolved by walking the underlying **1-minute path**.  That matters because
the dominant lie in bar-level backtests is same-bar stop/target ambiguity: on
a 15m bar it is entirely common for price to touch both a 1R stop and a 2R
target, and the backtester simply picks one.  At 1m resolution the true
sequence is usually visible; when it still isn't we resolve pessimistically
and *count* how often that happened, so the ambiguity is reportable rather
than hidden.

Two stages, deliberately separated:

``resolve``      every signal is simulated independently.  This measures the
                 raw edge of the idea, unclouded by portfolio constraints.
``apply_caps``   a chronological pass that enforces how many positions may be
                 open at once and how many trades a day is allowed.  This is
                 what an account could actually have traded.

Keeping them apart means a strategy that looks good only because the
concurrency filter happened to skip its losers cannot hide.

Conventions
-----------
* Prices in the bar arrays are **mid**.  Bid = mid - s/2, ask = mid + s/2.
* A long buys the ask and sells the bid; a short is the mirror.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .costs import CostModel

MARKET, LIMIT = 0, 1


@dataclass
class Signal:
    ts: int                # ms, close of the decision bar that produced it
    side: int              # +1 long, -1 short
    entry_px: float        # limit price (ignored for market entries)
    stop_px: float
    target_px: float
    entry_type: int = LIMIT
    expiry_ms: int = 30 * 60_000     # cancel a resting order after this
    max_hold_ms: int = 6 * 3600_000  # flatten an open trade after this
    tag: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class BacktestResult:
    trades: pd.DataFrame          # after concurrency caps
    raw_trades: pd.DataFrame      # every signal, resolved independently
    ambiguous: int
    signals: int
    expired: int
    capped: int


def _prepare(minutes: pd.DataFrame) -> dict:
    return {
        "ts": minutes["ts"].to_numpy(np.int64),
        "o": minutes["open"].to_numpy(np.float64),
        "h": minutes["high"].to_numpy(np.float64),
        "l": minutes["low"].to_numpy(np.float64),
        "c": minutes["close"].to_numpy(np.float64),
        "s": minutes["spread_med"].to_numpy(np.float64),
    }


def resolve(
    minutes: pd.DataFrame,
    signals: list[Signal],
    costs: CostModel,
    risk_per_trade: float = 100.0,
) -> tuple[pd.DataFrame, int, int]:
    """Simulate every signal independently. Returns (trades, ambiguous, expired)."""
    m = _prepare(minutes)
    ts, hi, lo, op, cl, sp = m["ts"], m["h"], m["l"], m["o"], m["c"], m["s"]
    n = len(ts)

    rows: list[dict] = []
    ambiguous = expired = 0

    for sig in sorted(signals, key=lambda s: s.ts):
        start = int(np.searchsorted(ts, sig.ts, side="right"))
        if start >= n:
            continue
        long = sig.side > 0

        # ---------------- pending order phase ----------------
        if sig.entry_type == MARKET:
            fill_idx = start
            half = costs.effective_spread(sp[start]) / 2.0
            fill_px = op[start] + (half + costs.entry_slippage) * sig.side
        else:
            fill_idx, fill_px = -1, np.nan
            deadline = sig.ts + sig.expiry_ms
            i = start
            while i < n and ts[i] <= deadline:
                half = costs.effective_spread(sp[i]) / 2.0
                if long:
                    if lo[i] + half <= sig.entry_px:      # ask reaches buy limit
                        fill_idx, fill_px = i, sig.entry_px
                        break
                else:
                    if hi[i] - half >= sig.entry_px:      # bid reaches sell limit
                        fill_idx, fill_px = i, sig.entry_px
                        break
                i += 1
            if fill_idx < 0:
                expired += 1
                continue

        risk_px = abs(fill_px - sig.stop_px)
        if risk_px <= 0 or not np.isfinite(risk_px):
            continue
        qty = risk_per_trade / risk_px

        # ---------------- open position phase ----------------
        stop_deadline = ts[fill_idx] + sig.max_hold_ms
        exit_idx, exit_px, reason = -1, np.nan, "timeout"
        j = fill_idx
        while j < n and ts[j] <= stop_deadline:
            half = costs.effective_spread(sp[j]) / 2.0
            if long:
                hit_stop = lo[j] - half <= sig.stop_px
                hit_tgt = hi[j] - half >= sig.target_px
            else:
                hit_stop = hi[j] + half >= sig.stop_px
                hit_tgt = lo[j] + half <= sig.target_px

            if hit_stop and hit_tgt:
                ambiguous += 1                     # unresolvable: assume the loss
                exit_idx, reason = j, "stop_ambiguous"
                exit_px = sig.stop_px - costs.stop_slippage * sig.side
                break
            if hit_stop:
                exit_idx, reason = j, "stop"
                exit_px = sig.stop_px - costs.stop_slippage * sig.side
                break
            if hit_tgt:
                exit_idx, reason = j, "target"
                exit_px = sig.target_px
                break
            j += 1

        if exit_idx < 0:
            exit_idx = min(j, n - 1)
            half = costs.effective_spread(sp[exit_idx]) / 2.0
            exit_px = cl[exit_idx] - (half + costs.entry_slippage) * sig.side

        gross = (exit_px - fill_px) * sig.side * qty
        pnl = gross - 2.0 * costs.commission_per_side * qty
        rows.append(
            {
                "signal_ts": sig.ts,
                "entry_ts": int(ts[fill_idx]),
                "exit_ts": int(ts[exit_idx]),
                "side": sig.side,
                "tag": sig.tag,
                "entry_px": fill_px,
                "stop_px": sig.stop_px,
                "target_px": sig.target_px,
                "exit_px": exit_px,
                "risk_px": risk_px,
                "qty": qty,
                "pnl": pnl,
                "r": pnl / risk_per_trade,
                "reason": reason,
                "hold_min": int((ts[exit_idx] - ts[fill_idx]) / 60_000),
                **sig.meta,
            }
        )

    trades = pd.DataFrame(rows)
    if len(trades):
        trades["entry_dt"] = pd.to_datetime(trades["entry_ts"], unit="ms", utc=True)
        trades["exit_dt"] = pd.to_datetime(trades["exit_ts"], unit="ms", utc=True)
    return trades, ambiguous, expired


def apply_caps(
    trades: pd.DataFrame,
    max_concurrent: int = 1,
    max_per_day: int | None = None,
    max_daily_loss_r: float | None = None,
) -> pd.DataFrame:
    """Chronological portfolio filter.

    ``max_daily_loss_r`` is the circuit breaker the original strategy had no
    equivalent of: once the day is down this many R, stop taking new trades.
    Gold's worst days are news days, and they cluster.
    """
    if trades is None or len(trades) == 0:
        return trades

    t = trades.sort_values("entry_ts").reset_index(drop=True)
    open_until: list[int] = []
    day_count: dict[pd.Timestamp, int] = {}
    day_pnl: dict[pd.Timestamp, float] = {}
    keep: list[int] = []

    for i, row in t.iterrows():
        start, end = row["entry_ts"], row["exit_ts"]
        day = row["entry_dt"].normalize()
        open_until = [e for e in open_until if e > start]

        if len(open_until) >= max_concurrent:
            continue
        if max_per_day is not None and day_count.get(day, 0) >= max_per_day:
            continue
        if max_daily_loss_r is not None and day_pnl.get(day, 0.0) <= -abs(max_daily_loss_r):
            continue

        keep.append(i)
        open_until.append(end)
        day_count[day] = day_count.get(day, 0) + 1
        day_pnl[day] = day_pnl.get(day, 0.0) + row["r"]

    return t.loc[keep].reset_index(drop=True)


def run(
    minutes: pd.DataFrame,
    signals: list[Signal],
    costs: CostModel,
    risk_per_trade: float = 100.0,
    max_concurrent: int = 1,
    max_per_day: int | None = None,
    max_daily_loss_r: float | None = None,
) -> BacktestResult:
    raw, ambiguous, expired = resolve(minutes, signals, costs, risk_per_trade)
    capped = apply_caps(raw, max_concurrent, max_per_day, max_daily_loss_r)
    return BacktestResult(
        trades=capped,
        raw_trades=raw,
        ambiguous=ambiguous,
        signals=len(signals),
        expired=expired,
        capped=(len(raw) - len(capped)) if len(raw) else 0,
    )
