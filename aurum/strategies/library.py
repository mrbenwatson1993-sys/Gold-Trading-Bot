"""The hypothesis set.

Each function is one falsifiable claim about gold's intraday behaviour.  They
are deliberately simple: the goal of the research pass is to find out which
*mechanisms* survive realistic costs, not to produce a finely tuned curve.
Tuning comes later, and only on whatever survives.

Sessions are in UTC:
    Asian     23:00 - 07:00
    London    07:00 - 16:00   (LBMA fixes 10:30 and 15:00 London time)
    New York  13:00 - 21:00   (US data 13:30, COMEX pit open 13:20)
    Overlap   13:00 - 16:00   <- gold's deepest liquidity
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..engine.backtest import LIMIT, MARKET, Signal
from .base import RiskSpec, make_signal, session_mask


# --------------------------------------------------------------------------
# H1. Opening range breakout
# --------------------------------------------------------------------------
def opening_range_breakout(
    df: pd.DataFrame,
    spec: RiskSpec,
    open_min: int,        # session start, minutes since UTC midnight
    range_min: int = 30,  # length of the opening range
    window_min: int = 240,  # how long after the range we accept a break
    min_range_atr: float = 0.4,
    max_range_atr: float = 3.0,
    one_per_session: bool = True,
    tag: str = "ORB",
) -> list[Signal]:
    """Break of the session's opening range, confirmed on a bar close.

    Rationale: gold's session opens carry a genuine order-flow event (London
    physical desks, COMEX pit).  A range that forms then breaks is the market
    resolving an imbalance, not a chart pattern.

    We require the range to be *neither* too tight nor too wide relative to
    ATR: a tight range breaks on noise, a wide one leaves no room to the target.
    """
    out: list[Signal] = []
    range_end = open_min + range_min
    window_end = range_end + window_min

    for _, day in df.groupby("date", sort=True):
        in_range = day[(day["mins_utc"] >= open_min) & (day["mins_utc"] < range_end)]
        if len(in_range) < 2:
            continue
        hi, lo = in_range["high"].max(), in_range["low"].min()
        width = hi - lo
        if not np.isfinite(width) or width <= 0:
            continue

        after = day[(day["mins_utc"] >= range_end) & (day["mins_utc"] < window_end)]
        fired = False
        for _, bar in after.iterrows():
            atr = bar["atr14"]
            if not np.isfinite(atr) or atr <= 0:
                continue
            if not (min_range_atr <= width / atr <= max_range_atr):
                break  # range quality is a property of the day, not the bar
            side = 0
            if bar["close"] > hi:
                side = 1
            elif bar["close"] < lo:
                side = -1
            if side == 0:
                continue
            sig = make_signal(
                bar["ts"], side, bar["close"], atr, spec, tag,
                entry_type=MARKET, bar_range=float(bar["range"]),
                meta={"range_atr": width / atr, "session_min": open_min},
            )
            if sig:
                out.append(sig)
            fired = True
            if one_per_session:
                break
        del fired
    return out


# --------------------------------------------------------------------------
# H2. Asian range -> London expansion
# --------------------------------------------------------------------------
def asian_range_break(
    df: pd.DataFrame,
    spec: RiskSpec,
    asia_start: int = 23 * 60,
    asia_end: int = 7 * 60,
    trade_start: int = 7 * 60,
    trade_end: int = 16 * 60,
    max_range_atr: float = 2.5,
    tag: str = "ASIA_BREAK",
) -> list[Signal]:
    """Break of the (quiet) Asian range during (busy) London hours.

    Rationale: the Asian session is thin and range-bound; London arrives with
    real volume and resolves the range.  This is the single most widely traded
    gold setup, which is a reason to be *sceptical* -- crowded setups decay.
    Testing it is how we find out whether it still pays after costs.
    """
    out: list[Signal] = []
    # Asian session wraps midnight, so key it to the London date that follows.
    d = df.copy()
    d["sess_date"] = np.where(
        d["mins_utc"] >= asia_start, d["date"] + pd.Timedelta(days=1), d["date"]
    )

    for _, day in d.groupby("sess_date", sort=True):
        rng = day[session_mask(day, asia_start, asia_end)]
        if len(rng) < 10:
            continue
        hi, lo = rng["high"].max(), rng["low"].min()
        width = hi - lo
        if not np.isfinite(width) or width <= 0:
            continue

        trade = day[(day["mins_utc"] >= trade_start) & (day["mins_utc"] < trade_end)]
        for _, bar in trade.iterrows():
            atr = bar["atr14"]
            if not np.isfinite(atr) or atr <= 0 or width / atr > max_range_atr:
                break
            side = 1 if bar["close"] > hi else (-1 if bar["close"] < lo else 0)
            if side == 0:
                continue
            sig = make_signal(
                bar["ts"], side, bar["close"], atr, spec, tag,
                entry_type=MARKET, bar_range=float(bar["range"]), meta={"range_atr": width / atr},
            )
            if sig:
                out.append(sig)
            break
    return out


# --------------------------------------------------------------------------
# H3. Trend pullback  (the cleaned-up core of Candidate B)
# --------------------------------------------------------------------------
def trend_pullback(
    df: pd.DataFrame,
    spec: RiskSpec,
    trade_start: int = 7 * 60,
    trade_end: int = 20 * 60,
    require_slope: bool = True,
    tag: str = "PULLBACK",
) -> list[Signal]:
    """EMA-trend pullback with a close-based trigger.

    This is your Candidate B idea stripped to its mechanism: trade with the
    higher-timeframe trend, enter on a pullback to the fast EMA, trigger on a
    close back in the trend direction.  Everything discretionary in the
    original -- the 15-point score, the pattern zoo, the RSI band -- is gone,
    because none of it was derived from data.
    """
    out: list[Signal] = []
    d = df
    up = (d["ema20"] > d["ema50"]) & (d["ema50"] > d["ema200"])
    dn = (d["ema20"] < d["ema50"]) & (d["ema50"] < d["ema200"])
    if require_slope:
        up &= d["ema20"] > d["ema20"].shift(3)
        dn &= d["ema20"] < d["ema20"].shift(3)

    touched_up = (d["low"] <= d["ema20"]) & (d["close"] > d["ema20"])
    touched_dn = (d["high"] >= d["ema20"]) & (d["close"] < d["ema20"])
    hours = (d["mins_utc"] >= trade_start) & (d["mins_utc"] < trade_end)

    long_sig = up & touched_up & hours & (d["close"] > d["open"])
    short_sig = dn & touched_dn & hours & (d["close"] < d["open"])

    for side, mask in ((1, long_sig), (-1, short_sig)):
        for _, bar in d[mask].iterrows():
            sig = make_signal(
                bar["ts"], side, bar["close"], bar["atr14"], spec, tag,
                entry_type=MARKET, bar_range=float(bar["range"]),
            )
            if sig:
                out.append(sig)
    return out


# --------------------------------------------------------------------------
# H4. Momentum ignition / volatility expansion
# --------------------------------------------------------------------------
def volatility_expansion(
    df: pd.DataFrame,
    spec: RiskSpec,
    lookback: int = 24,
    expansion: float = 1.6,
    trade_start: int = 7 * 60,
    trade_end: int = 20 * 60,
    tag: str = "EXPANSION",
) -> list[Signal]:
    """Trade in the direction of a bar that breaks recent range on expansion.

    Rationale: gold's intraday moves are strongly clustered in time.  A bar
    whose range materially exceeds the recent norm *and* closes through the
    N-bar extreme marks a genuine repricing rather than noise.
    """
    out: list[Signal] = []
    d = df
    big = d["range"] > expansion * d["range"].rolling(lookback).mean()
    strong = d["body_pct"] >= 0.55
    hours = (d["mins_utc"] >= trade_start) & (d["mins_utc"] < trade_end)

    up = big & strong & hours & (d["close"] > d[f"hh{lookback}"]) & (d["close"] > d["open"])
    dn = big & strong & hours & (d["close"] < d[f"ll{lookback}"]) & (d["close"] < d["open"])

    for side, mask in ((1, up), (-1, dn)):
        for _, bar in d[mask].iterrows():
            sig = make_signal(
                bar["ts"], side, bar["close"], bar["atr14"], spec, tag,
                entry_type=MARKET, bar_range=float(bar["range"]),
            )
            if sig:
                out.append(sig)
    return out


# --------------------------------------------------------------------------
# H5. Mean reversion from a stretched move
# --------------------------------------------------------------------------
def stretch_fade(
    df: pd.DataFrame,
    spec: RiskSpec,
    stretch_atr: float = 2.0,
    max_atr_ratio: float = 1.3,
    trade_start: int = 7 * 60,
    trade_end: int = 20 * 60,
    tag: str = "FADE",
) -> list[Signal]:
    """Fade an over-extension from the mean in a *non*-trending regime.

    The counterpart hypothesis to H3/H4: if gold trends intraday, pullback and
    breakout pay and this loses.  If it ranges, this pays and they lose.  We
    test both rather than assuming.
    """
    out: list[Signal] = []
    d = df
    stretch = (d["close"] - d["ema50"]) / d["atr14"].replace(0, np.nan)
    calm = d["atr_ratio"] <= max_atr_ratio
    flat = (d["ema50"] - d["ema200"]).abs() < 0.5 * d["atr14"]
    hours = (d["mins_utc"] >= trade_start) & (d["mins_utc"] < trade_end)

    up = (stretch <= -stretch_atr) & calm & flat & hours & (d["close"] > d["open"])
    dn = (stretch >= stretch_atr) & calm & flat & hours & (d["close"] < d["open"])

    for side, mask in ((1, up), (-1, dn)):
        for _, bar in d[mask].iterrows():
            sig = make_signal(
                bar["ts"], side, bar["close"], bar["atr14"], spec, tag,
                entry_type=MARKET, bar_range=float(bar["range"]),
            )
            if sig:
                out.append(sig)
    return out


# --------------------------------------------------------------------------
# H6. Reaction-zone retest  (your best original idea, rebuilt)
# --------------------------------------------------------------------------
def reaction_zone_retest(
    df: pd.DataFrame,
    spec: RiskSpec,
    pivot_lr: int = 3,
    cluster_atr: float = 0.25,
    min_touches: int = 2,
    max_age_bars: int = 200,
    trade_start: int = 7 * 60,
    trade_end: int = 20 * 60,
    tag: str = "ZONE",
) -> list[Signal]:
    """Levels that have already produced multiple reactions, traded on retest.

    This keeps what was genuinely good in your V1.9.3 engine -- a neutral
    price cluster whose role is inferred from which side price is currently
    accepting, rather than a box permanently stamped "supply" or "demand" --
    and fixes the three bugs it shipped with:

    * age is counted in **bars**, not wall-clock milliseconds (the original
      expired every Friday level over the weekend);
    * eviction is by **importance**, not arrival order;
    * the flip-retest timeout can't disable itself.
    """
    out: list[Signal] = []
    d = df.reset_index(drop=False)
    n = len(d)
    hi, lo = d["high"].to_numpy(), d["low"].to_numpy()
    close, atr = d["close"].to_numpy(), d["atr14"].to_numpy()
    ts = d["ts"].to_numpy()
    mins = d["mins_utc"].to_numpy()

    # Confirmed pivots: extremes with `pivot_lr` bars either side.
    piv_hi = np.zeros(n, bool)
    piv_lo = np.zeros(n, bool)
    for i in range(pivot_lr, n - pivot_lr):
        w_h, w_l = hi[i - pivot_lr:i + pivot_lr + 1], lo[i - pivot_lr:i + pivot_lr + 1]
        piv_hi[i] = hi[i] == w_h.max()
        piv_lo[i] = lo[i] == w_l.min()

    # zones: [price, touches, last_bar]
    zones: list[list[float]] = []
    last_trade_bar = -10_000

    for i in range(pivot_lr, n):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        # A pivot only becomes known `pivot_lr` bars after it printed.
        j = i - pivot_lr
        if j >= 0 and (piv_hi[j] or piv_lo[j]):
            px = hi[j] if piv_hi[j] else lo[j]
            merged = False
            for z in zones:
                if abs(z[0] - px) <= cluster_atr * a:
                    z[0] = (z[0] * z[1] + px) / (z[1] + 1)
                    z[1] += 1
                    z[2] = j
                    merged = True
                    break
            if not merged:
                zones.append([px, 1.0, float(j)])

        # Drop stale zones; cap by importance (touch count, then recency).
        zones = [z for z in zones if i - z[2] <= max_age_bars]
        if len(zones) > 40:
            zones.sort(key=lambda z: (z[1], z[2]), reverse=True)
            zones = zones[:40]

        if not (trade_start <= mins[i] < trade_end) or i - last_trade_bar < 6:
            continue

        for z in zones:
            if z[1] < min_touches or i - z[2] < 3:
                continue
            level, touches = z[0], z[1]
            band = cluster_atr * a
            # Rejection from below the level -> short; from above -> long.
            if lo[i] <= level + band and lo[i] >= level - band * 3 and close[i] > level + band * 0.5:
                side = 1
            elif hi[i] >= level - band and hi[i] <= level + band * 3 and close[i] < level - band * 0.5:
                side = -1
            else:
                continue
            sig = make_signal(
                ts[i], side, close[i], a, spec, tag,
                entry_type=MARKET, bar_range=float(hi[i]-lo[i]), meta={"touches": int(touches)},
            )
            if sig:
                out.append(sig)
                last_trade_bar = i
            break
    return out


# --------------------------------------------------------------------------
# H7. Intraday momentum  (Gao, Han, Li & Zhou, JFE 2018)
# --------------------------------------------------------------------------
def intraday_momentum(
    df: pd.DataFrame,
    spec: RiskSpec,
    anchor_min: int = 13 * 60,     # measure the move from here...
    signal_min: int = 17 * 60,     # ...decide here
    min_move_atr: float = 0.5,
    tag: str = "IMOM",
) -> list[Signal]:
    """Direction of the day's move so far predicts the rest of the session.

    A peer-reviewed effect in equity indices, extended to commodities.  It only
    produces one trade per day, so it can never be the whole system -- but if
    it holds on gold it is a genuinely independent return stream.
    """
    out: list[Signal] = []
    for _, day in df.groupby("date", sort=True):
        anchor = day[day["mins_utc"] >= anchor_min]
        if len(anchor) < 2:
            continue
        a_px = anchor.iloc[0]["open"]
        decide = day[day["mins_utc"] >= signal_min]
        if len(decide) < 2:
            continue
        bar = decide.iloc[0]
        atr = bar["atr14"]
        if not np.isfinite(atr) or atr <= 0:
            continue
        move = bar["close"] - a_px
        if abs(move) < min_move_atr * atr:
            continue
        side = 1 if move > 0 else -1
        sig = make_signal(bar["ts"], side, bar["close"], atr, spec, tag,
                          entry_type=MARKET, bar_range=float(bar["range"]))
        if sig:
            out.append(sig)
    return out


# --------------------------------------------------------------------------
# H8. Failed breakout / liquidity sweep reversal
# --------------------------------------------------------------------------
def sweep_reversal(
    df: pd.DataFrame,
    spec: RiskSpec,
    lookback: int = 24,
    min_poke_atr: float = 0.15,
    max_poke_atr: float = 2.0,
    trade_start: int = 7 * 60,
    trade_end: int = 20 * 60,
    tag: str = "SWEEP",
) -> list[Signal]:
    """Price takes out an N-bar extreme, then closes back inside: fade it.

    This is the mirror of H1/H4.  Measurement says gold's intraday returns are
    mildly *negatively* autocorrelated, so the breakout is the losing side of
    the trade and the reclaim is the winning one.  Mechanically it is the
    stop-run: resting orders above the high get filled by a poke, and once
    that liquidity is consumed price has no reason to stay up there.

    Requiring the poke to be neither trivial nor enormous matters -- a 0.05
    ATR poke is noise, a 2 ATR poke is a real repricing we should not fade.
    """
    out: list[Signal] = []
    d = df
    hh, ll = d[f"hh{lookback}"], d[f"ll{lookback}"]
    atr = d["atr14"]
    hours = (d["mins_utc"] >= trade_start) & (d["mins_utc"] < trade_end)

    poke_up = (d["high"] - hh) / atr
    poke_dn = (ll - d["low"]) / atr

    short = (
        hours
        & (d["high"] > hh)
        & (d["close"] < hh)
        & (d["close"] < d["open"])
        & poke_up.between(min_poke_atr, max_poke_atr)
    )
    long = (
        hours
        & (d["low"] < ll)
        & (d["close"] > ll)
        & (d["close"] > d["open"])
        & poke_dn.between(min_poke_atr, max_poke_atr)
    )

    for side, mask in ((1, long), (-1, short)):
        for _, bar in d[mask].iterrows():
            sig = make_signal(
                bar["ts"], side, bar["close"], bar["atr14"], spec, tag,
                entry_type=MARKET, bar_range=float(bar["range"]),
                meta={"poke_atr": float(
                    poke_dn.loc[bar.name] if side > 0 else poke_up.loc[bar.name])},
            )
            if sig:
                out.append(sig)
    return out


# --------------------------------------------------------------------------
# H9. Session VWAP reversion
# --------------------------------------------------------------------------
def vwap_reversion(
    df: pd.DataFrame,
    spec: RiskSpec,
    stretch: float = 2.0,
    anchor_min: int = 7 * 60,
    trade_start: int = 8 * 60,
    trade_end: int = 20 * 60,
    tag: str = "VWAPREV",
) -> list[Signal]:
    """Fade extension from the session VWAP.

    VWAP is where the session's actual volume traded, so it is the session's
    fair value in the most literal sense.  We use tick count as the volume
    weight (Dukascopy gives no true volume for spot gold, and tick count is a
    good intraday proxy).
    """
    out: list[Signal] = []
    d = df.copy()
    tp = (d["high"] + d["low"] + d["close"]) / 3.0
    w = d["ticks"].clip(lower=1)

    in_sess = d["mins_utc"] >= anchor_min
    grp = d["date"]
    num = (tp * w).where(in_sess, 0).groupby(grp).cumsum()
    den = w.where(in_sess, 0).groupby(grp).cumsum().replace(0, np.nan)
    d["vwap"] = num / den
    d["dev"] = (d["close"] - d["vwap"]) / d["atr14"].replace(0, np.nan)

    hours = (d["mins_utc"] >= trade_start) & (d["mins_utc"] < trade_end)
    long = hours & (d["dev"] <= -stretch) & (d["close"] > d["open"])
    short = hours & (d["dev"] >= stretch) & (d["close"] < d["open"])

    for side, mask in ((1, long), (-1, short)):
        for _, bar in d[mask].iterrows():
            sig = make_signal(
                bar["ts"], side, bar["close"], bar["atr14"], spec, tag,
                entry_type=MARKET, bar_range=float(bar["range"]), meta={"dev": float(bar["dev"])},
            )
            if sig:
                out.append(sig)
    return out


# --------------------------------------------------------------------------
# H10. Daily trend following
# --------------------------------------------------------------------------
def daily_trend(
    df: pd.DataFrame,
    spec: RiskSpec,
    ma_len: int = 50,
    confirm_bars: int = 1,
    tag: str = "DTREND",
) -> list[Signal]:
    """Enter when price crosses its moving average; ride with a trailing stop.

    This is the horizon where gold actually pays.  Intraday, variance ratios sit
    at ~1.0 and there is nothing systematic to extract; on daily bars simple
    trend rules produce a materially better Sharpe than buy-and-hold, and hold
    up across a wide range of lookbacks rather than at one lucky setting.

    The economics are completely different from an intraday system.  A $0.80
    round trip against a multi-week move worth $60 is about 1% of the move.
    The same $0.80 against an intraday $8 stop is 10% of risk.  Cost stops
    being the dominant term, which is why this works and the 15m versions do
    not.

    Expects ``df`` to be daily bars.  ``spec.trail_atr`` should be non-zero:
    a fixed target defeats the point of trend following.
    """
    out: list[Signal] = []
    d = df.copy()
    ma = d["close"].rolling(ma_len).mean()
    above = d["close"] > ma

    # Require `confirm_bars` consecutive closes on the new side before acting,
    # which cuts the whipsaw trades that cluster around a flat MA.
    stable = above.rolling(confirm_bars).apply(lambda x: x.all() or not x.any(), raw=True)
    cross_up = above & ~above.shift(1).fillna(False) & (stable == 1)
    cross_dn = ~above & above.shift(1).fillna(False) & (stable == 1)

    for side, mask in ((1, cross_up), (-1, cross_dn)):
        for _, bar in d[mask.fillna(False)].iterrows():
            atr = bar["atr14"]
            if not np.isfinite(atr) or atr <= 0:
                continue
            sig = make_signal(
                bar["ts"], side, bar["close"], atr, spec, tag,
                entry_type=MARKET, bar_range=float(bar["range"]),
                meta={"ma_len": ma_len},
            )
            if sig:
                out.append(sig)
    return out
