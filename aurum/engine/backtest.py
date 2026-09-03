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


@dataclass(frozen=True)
class Ladder:
    """A step-trailing ("ladder") exit policy.

    ``steps`` is an ordered sequence of ``(trigger_r, lock_r)`` rungs: once the
    trade's favourable excursion reaches ``trigger_r`` multiples of initial
    risk, the protective stop ratchets to ``lock_r`` (0.0 = breakeven, negative
    = still at a loss but reduced, positive = profit locked). The stop only ever
    moves in the trade's favour.

    ``trail_atr`` optionally engages a continuous ATR trail once the final rung
    is armed, so the ladder secures the early move and then lets the tail run.

    ``give_back_frac`` is an alternative continuous rule: trail at a fixed
    fraction of the best excursion so far, which adapts to how far the trade has
    actually travelled rather than to volatility.
    """
    steps: tuple = ()
    trail_atr: float = 0.0
    give_back_frac: float = 0.0
    target_r: float = 0.0          # 0 = no fixed target (let the ladder decide)

    @property
    def name(self) -> str:
        if not self.steps and not self.trail_atr and not self.give_back_frac:
            return f"fixed {self.target_r:g}R"
        parts = []
        if self.steps:
            parts.append("+".join(f"{t:g}->{l:g}" for t, l in self.steps))
        if self.trail_atr:
            parts.append(f"trail{self.trail_atr:g}atr")
        if self.give_back_frac:
            parts.append(f"keep{1 - self.give_back_frac:.0%}")
        if self.target_r:
            parts.append(f"tp{self.target_r:g}R")
        return " ".join(parts)


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
    # --- exit management (0 disables) ---------------------------------------
    # Move the stop to breakeven once price has travelled this many R in our
    # favour. Cuts the left tail; also converts some winners into scratches.
    breakeven_r: float = 0.0
    # Trail the stop by this many ATR once the trade is in profit, instead of
    # holding a fixed stop. Lets winners run past the fixed target.
    trail_atr: float = 0.0
    atr: float = 0.0        # ATR at signal time, for the trail
    ladder: "Ladder | None" = None   # step-trailing policy; overrides the above


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

        # Size and account in R against the stop distance the signal PLANNED,
        # not the one that survived slippage. A trader picks the lot size before
        # the fill comes back; if the entry slips halfway to the stop, the loss
        # is smaller in dollars but the position is not bigger. Sizing off the
        # realised distance instead lets a badly-slipped fill claim an enormous
        # position and a nonsense R multiple - three trades in the out-of-sample
        # log filled within $0.14 of their stop and were being scored on a
        # sixty-fold inflated size. It also makes the ladder rungs sit where the
        # Pine implementation puts them, which is at ATR-derived distances.
        plan_px = abs(sig.entry_px - sig.stop_px)
        fill_risk = abs(fill_px - sig.stop_px)
        risk_px = plan_px if plan_px > 0 and np.isfinite(plan_px) else fill_risk
        if risk_px <= 0 or not np.isfinite(risk_px) or fill_risk <= 0:
            continue
        qty = risk_per_trade / risk_px

        # ---------------- open position phase ----------------
        stop_deadline = ts[fill_idx] + sig.max_hold_ms
        exit_idx, exit_px, reason = -1, np.nan, "timeout"
        stop_now = sig.stop_px
        be_done = False
        lad = sig.ladder
        rungs = list(lad.steps) if lad else []
        armed = 0                     # how many rungs have fired
        best_exc = 0.0                # best favourable excursion on CLOSES, in R
        peak_exc = 0.0                # best excursion on extremes, reporting only

        if lad is not None:
            trail_dist = lad.trail_atr * sig.atr if (lad.trail_atr > 0 and sig.atr > 0) else 0.0
            give_back = lad.give_back_frac
            use_target = (fill_px + lad.target_r * risk_px * sig.side) if lad.target_r > 0 else np.nan
        else:
            trail_dist = sig.trail_atr * sig.atr if (sig.trail_atr > 0 and sig.atr > 0) else 0.0
            give_back = 0.0
            use_target = sig.target_px if trail_dist <= 0 else np.nan

        j = fill_idx
        while j < n and ts[j] <= stop_deadline:
            half = costs.effective_spread(sp[j]) / 2.0
            if long:
                bid_hi, bid_lo = hi[j] - half, lo[j] - half
                hit_stop = bid_lo <= stop_now
                hit_tgt = (not np.isnan(use_target)) and bid_hi >= use_target
            else:
                ask_hi, ask_lo = hi[j] + half, lo[j] + half
                hit_stop = ask_hi >= stop_now
                hit_tgt = (not np.isnan(use_target)) and ask_lo <= use_target

            if hit_stop and hit_tgt:
                ambiguous += 1                     # unresolvable: assume the loss
                exit_idx, reason = j, "stop_ambiguous"
                exit_px = stop_now - costs.stop_slippage * sig.side
                break
            if hit_stop:
                exit_idx = j
                # Name the exit by which rung was protecting it, so the trade
                # log shows what the ladder actually did.
                locked = (stop_now - fill_px) * sig.side / risk_px
                reason = ("stop" if locked < -0.02 else
                          "breakeven" if abs(locked) <= 0.02 else
                          f"ladder_lock_{locked:.2f}R")
                exit_px = stop_now - costs.stop_slippage * sig.side
                break
            if hit_tgt:
                exit_idx, reason = j, "target"
                exit_px = use_target
                break

            # --- ratchet on CLOSED-BAR information -----------------------
            # The stop is moved using the bar's close, not its running extreme,
            # for two reasons. It is what a live implementation can actually do
            # (you learn the bar's high only once the bar is over, and by then
            # price has left it). And it removes the intrabar ordering problem:
            # a stop derived from the close cannot have been hit earlier in the
            # same bar, because the close is the last event in it. So the new
            # level legitimately takes effect from the next bar.
            #
            # Ratcheting off the high instead looks far better and is fiction:
            # it banked +0.076 R per trade on coin-flip entries at zero cost,
            # where the true answer is zero.
            stop_before = stop_now
            bar_close = cl[j]
            excursion = (bar_close - fill_px) * sig.side
            best_exc = max(best_exc, excursion / risk_px)
            # Peak excursion from the extremes is still recorded, for reporting
            # only -- it never drives an exit.
            peak_exc = max(peak_exc, ((bid_hi - fill_px) if long else (fill_px - ask_lo)) / risk_px)

            for t_r, lock_r in rungs[armed:]:
                if best_exc >= t_r:
                    cand = fill_px + lock_r * risk_px * sig.side
                    stop_now = max(stop_now, cand) if long else min(stop_now, cand)
                    armed += 1
                    be_done = True
                else:
                    break

            if give_back > 0 and best_exc > 0:
                cand = fill_px + best_exc * (1.0 - give_back) * risk_px * sig.side
                stop_now = max(stop_now, cand) if long else min(stop_now, cand)

            if trail_dist > 0 and armed >= len(rungs) and excursion > 0:
                cand = (bar_close - trail_dist) if long else (bar_close + trail_dist)
                stop_now = max(stop_now, cand) if long else min(stop_now, cand)

            if sig.breakeven_r > 0 and not be_done and best_exc >= sig.breakeven_r:
                cand = fill_px
                stop_now = max(stop_now, cand) if long else min(stop_now, cand)
                be_done = True

            # A close-derived stop takes effect from the next bar; no same-bar
            # test is needed, and adding one would double-count the bar we just
            # measured the close from.
            del stop_before
            j += 1

        if exit_idx < 0:
            # Held to the time limit (or ran out of data): flatten at market.
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
                "mfe_r": peak_exc,
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
