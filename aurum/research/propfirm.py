"""What prop-firm rules actually cost this strategy.

The bot's out-of-sample record was earned with a median hold of 12.8 hours:
61% of its trades were open across at least one daily rollover and a third ran
past 24 hours.  Prop firms constrain exactly that.  Rather than reason about it,
this module re-runs the shipped V6 configuration under each constraint and
measures the damage.

Four things are modelled that a normal backtest ignores:

**Session policies.**  ``flat_friday`` closes everything before the weekend
gap; ``no_overnight`` closes before the daily 21:00 UTC rollover; ``hold_24h``
and ``hold_8h`` simply shorten the time stop.  Each is applied by shortening the
individual signal's ``max_hold_ms``, so the engine flattens at the deadline the
same way it handles any timeout - no special-casing inside the simulator.

**Swap.**  Holding long gold overnight costs money: the forward curve is in
contango, so a long pays roughly (carry rate x price / 365) per ounce per night,
tripled on Wednesday.  Ignoring it flatters every long-only overnight system,
this one included.  Nights are counted at the 21:00 UTC rollover.

**Floating equity.**  Prop drawdown rules are breached on *unrealised* equity,
not on the closed-trade curve.  So the account is marked to market minute by
minute off the same 1-minute path the fills came from.

**Failure, not drawdown.**  A prop account does not "recover" from a breach; it
is dead.  So the daily-loss and max-drawdown limits are evaluated as pass/fail
against a real rule set, and the interesting output is the probability of
surviving to a profit target, not the average return.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.bars import add_features, resample
from ..data.dukascopy import load_minutes
from ..engine import costs as cost_presets
from ..engine.backtest import MARKET, Ladder, Signal, apply_caps, resolve
from ..engine.metrics import summarise
from .grid import ENTRIES, htf_bias

# The shipped V6 configuration.
ENTRY_NAMES = ("dip_unconfirmed", "breakout_24")
LADDER = Ladder(steps=((1.5, 0.0), (3.0, 1.5), (5.0, 3.2)))
STOP_ATR, MIN_STOP, MAX_STOP = 2.0, 8.0, 200.0
MAX_CONC, DAILY_LOSS_CAP_R = 5, 4.0
BASE_HOLD_H = 48
OOS_START = "2023-01-01"

ROLLOVER_HOUR = 21          # 17:00 New York, the industry standard rollover
CARRY_RATE = 0.045          # annualised cost of carry embedded in gold forwards


# ---------------------------------------------------------------------------
# session policies
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Policy:
    name: str
    hold_h: float = BASE_HOLD_H
    flat_daily: bool = False     # close before the 21:00 UTC rollover
    flat_weekend: bool = False   # close before Friday 20:00 UTC

    def deadline_ms(self, ts_ms: int) -> int:
        """Latest exit time for a signal fired at ``ts_ms``."""
        out = ts_ms + int(self.hold_h * 3600_000)
        t = pd.Timestamp(ts_ms, unit="ms", tz="UTC")
        if self.flat_daily:
            cut = t.normalize() + pd.Timedelta(hours=ROLLOVER_HOUR - 1)
            if cut <= t:
                cut += pd.Timedelta(days=1)
            out = min(out, int(cut.value // 1_000_000))
        if self.flat_weekend:
            # Friday 20:00 UTC, an hour before the week's close.
            days = (4 - t.weekday()) % 7
            cut = t.normalize() + pd.Timedelta(days=days, hours=20)
            if cut <= t:
                cut += pd.Timedelta(days=7)
            out = min(out, int(cut.value // 1_000_000))
        return out


POLICIES = [
    Policy("as_shipped (48h)"),
    Policy("flat_by_friday", flat_weekend=True),
    Policy("hold_24h", hold_h=24),
    Policy("hold_24h_flat_fri", hold_h=24, flat_weekend=True),
    Policy("no_overnight (intraday)", hold_h=48, flat_daily=True),
    Policy("hold_8h", hold_h=8),
]


# ---------------------------------------------------------------------------
# signal construction
# ---------------------------------------------------------------------------
def build_signals(bars: pd.DataFrame, bias: pd.Series, pol: Policy) -> list[Signal]:
    out: list[Signal] = []
    seen: set[int] = set()
    for nm in ENTRY_NAMES:
        L, _, _ = ENTRIES[nm](bars)
        L = (L & (bias >= 1)).fillna(False)
        for _, bar in bars[L].iterrows():
            atr = float(bar["atr14"])
            if not np.isfinite(atr) or atr <= 0:
                continue
            ts = int(bar["ts"])
            if ts in seen:
                continue
            seen.add(ts)
            dist = float(np.clip(atr * STOP_ATR, MIN_STOP, MAX_STOP))
            px = float(bar["close"])
            hold = max(pol.deadline_ms(ts) - ts, 30 * 60_000)
            out.append(Signal(
                ts=ts, side=1, entry_px=px,
                stop_px=px - dist, target_px=px + dist * 99,
                entry_type=MARKET, max_hold_ms=hold,
                atr=atr, ladder=LADDER, tag=nm,
            ))
    return sorted(out, key=lambda s: s.ts)


# ---------------------------------------------------------------------------
# swap
# ---------------------------------------------------------------------------
def rollovers_crossed(entry_dt: pd.Timestamp, exit_dt: pd.Timestamp) -> float:
    """Swap units charged, counting Wednesday's rollover triple."""
    cut = entry_dt.normalize() + pd.Timedelta(hours=ROLLOVER_HOUR)
    if cut <= entry_dt:
        cut += pd.Timedelta(days=1)
    units = 0.0
    while cut < exit_dt:
        if cut.weekday() != 4 and cut.weekday() != 5:      # no roll into Sat/Sun
            units += 3.0 if cut.weekday() == 2 else 1.0
        cut += pd.Timedelta(days=1)
    return units


def charge_swap(t: pd.DataFrame, rate: float = CARRY_RATE) -> pd.DataFrame:
    """Deduct financing from every trade's R, in place on a copy."""
    t = t.copy()
    nights = np.array([rollovers_crossed(a, b)
                       for a, b in zip(t["entry_dt"], t["exit_dt"])])
    per_night = t["entry_px"].to_numpy() * rate / 365.0        # $/oz/night
    t["swap_nights"] = nights
    t["swap_r"] = nights * per_night / t["risk_px"].to_numpy()
    t["r_gross"] = t["r"]
    t["r"] = t["r"] - t["swap_r"]
    return t


# ---------------------------------------------------------------------------
# prop account simulation on floating equity
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PropRules:
    name: str
    daily_loss_pct: float      # measured from start-of-day balance
    max_dd_pct: float          # from peak (trailing) or from start (static)
    trailing: bool = True
    profit_target_pct: float = 10.0


RULESETS = [
    PropRules("typical 2-step (5% daily / 10% static)", 5.0, 10.0, trailing=False),
    PropRules("trailing-DD (5% daily / 6% trailing)", 5.0, 6.0, trailing=True),
    PropRules("strict 1-step (4% daily / 6% trailing)", 4.0, 6.0, trailing=True),
]


def floating_equity(minutes: pd.DataFrame, trades: pd.DataFrame,
                    risk_pct: float) -> pd.Series:
    """Minute-by-minute account equity in % of starting balance.

    Realised P&L accrues at each exit; open positions are marked at the 1-minute
    mid.  This is the series a prop firm's risk engine actually watches.
    """
    ts = minutes["ts"].to_numpy(np.int64)
    mid = minutes["close"].to_numpy(np.float64)
    float_r = np.zeros(len(ts))
    real_r = np.zeros(len(ts))

    for _, row in trades.iterrows():
        i = int(np.searchsorted(ts, row["entry_ts"], "left"))
        j = int(np.searchsorted(ts, row["exit_ts"], "left"))
        if j <= i:
            j = min(i + 1, len(ts) - 1)
        seg = (mid[i:j] - row["entry_px"]) * row["side"] / row["risk_px"]
        # financing accrues while the position is open, not at the exit
        if "swap_r" in trades.columns and j > i:
            seg = seg - row["swap_r"] * np.linspace(0, 1, j - i)
        float_r[i:j] += seg
        if j < len(real_r):
            real_r[j:] += row["r"]

    eq = (real_r + float_r) * risk_pct
    return pd.Series(eq, index=minutes.index)


def run_account(eq: pd.Series, rules: PropRules,
                start_of_day: np.ndarray | None = None) -> dict:
    """Walk the equity curve under one rule set until it passes or dies.

    Everything reported is measured **up to the terminal event**. A prop account
    that breaches is closed, so drawdown it would have suffered afterwards is not
    drawdown it suffered.
    """
    v = eq.to_numpy()
    if start_of_day is None:
        day = eq.index.normalize()
        start_of_day = eq.groupby(day).transform("first").to_numpy()

    peak = np.maximum.accumulate(np.maximum(v, 0.0))
    dd_floor = (peak - rules.max_dd_pct) if rules.trailing else -rules.max_dd_pct
    daily_floor = start_of_day - rules.daily_loss_pct

    dead_dd = int(np.argmax(v <= dd_floor)) if (v <= dd_floor).any() else -1
    dead_day = int(np.argmax(v <= daily_floor)) if (v <= daily_floor).any() else -1
    hit = int(np.argmax(v >= rules.profit_target_pct)) if (v >= rules.profit_target_pct).any() else -1

    deaths = [i for i in (dead_dd, dead_day) if i >= 0]
    death = min(deaths) if deaths else -1

    if hit >= 0 and (death < 0 or hit < death):
        outcome, end = "passed", hit
    elif death >= 0:
        outcome = "failed_daily" if death == dead_day else "failed_maxdd"
        end = death
    else:
        outcome, end = "still_running", len(v) - 1

    lived = slice(0, end + 1)
    return {"outcome": outcome, "when": eq.index[end],
            "worst_intraday_pct": float((v[lived] - start_of_day[lived]).min()),
            "worst_dd_pct": float((peak[lived] - v[lived]).max()),
            "final_pct": float(v[end])}


def rolling_accounts(eq: pd.Series, rules: PropRules, every_days: int = 7) -> pd.DataFrame:
    """Start a fresh account every week; report how each one ends.

    One account over three years tells you almost nothing - it either survived or
    it didn't. Starting many overlapping accounts turns the same history into a
    distribution of outcomes, which is what a prop challenge actually is: you buy
    a start date, and the start date decides most of it.
    """
    day = eq.index.normalize()
    sod_full = eq.groupby(day).transform("first").to_numpy()
    day_codes = day.asi8

    starts = pd.date_range(eq.index[0], eq.index[-1] - pd.Timedelta(days=60),
                           freq=f"{every_days}D", tz="UTC")
    idx = np.searchsorted(eq.index.asi8, starts.asi8, "left")
    rows = []
    for k in idx:
        if len(eq) - k < 1000:
            continue
        base = eq.iloc[k]
        sub = eq.iloc[k:] - base
        sod = sod_full[k:] - base
        # the account's first (partial) day starts where the account starts
        first_day = day_codes[k:] == day_codes[k]
        sod = np.where(first_day, 0.0, sod)
        r = run_account(sub, rules, sod)
        r["start"] = eq.index[k].date()
        r["days"] = (r["when"] - eq.index[k]).days
        rows.append(r)
    return pd.DataFrame(rows)
