"""Live signal generation.

Deliberately shares its logic with the backtest rather than reimplementing it.
The most common way a researched strategy dies in production is a translation
bug between the study code and the live code, so ``latest_signal`` calls the
exact same functions in ``aurum.strategies.library`` that the walk-forward
validated.

This module is broker-agnostic.  It answers one question -- "given bars up to
now, is there a trade?" -- and leaves order placement to an adapter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import pandas as pd

from ..data.bars import add_features, resample
from ..strategies import library as lib
from ..strategies.base import RiskSpec


@dataclass
class LiveConfig:
    timeframe: str = "15min"
    stop_atr: float = 2.5
    target_r: float = 2.0
    min_stop_px: float = 5.0
    max_stop_px: float = 40.0
    trade_start_utc_min: int = 7 * 60
    trade_end_utc_min: int = 20 * 60
    max_hold_h: float = 8.0
    risk_per_trade_pct: float = 0.5
    max_trades_per_day: int = 5
    max_daily_loss_r: float = 3.0

    def spec(self) -> RiskSpec:
        return RiskSpec(
            stop_atr=self.stop_atr,
            target_r=self.target_r,
            min_stop_px=self.min_stop_px,
            max_stop_px=self.max_stop_px,
            entry_retrace=0.0,          # market-on-close; limits underperformed
            max_hold_h=self.max_hold_h,
        )


@dataclass
class Order:
    ts_utc: str
    side: str
    entry_type: str
    entry_px: float
    stop_px: float
    target_px: float
    qty: float
    risk_px: float
    tag: str

    def as_dict(self) -> dict:
        return asdict(self)


def latest_signal(
    minutes: pd.DataFrame,
    cfg: LiveConfig,
    equity: float,
    now: datetime | None = None,
    max_age_min: int = 2,
) -> Order | None:
    """Return an Order if the most recently *closed* bar produced a signal.

    ``max_age_min`` guards against acting on a stale bar: if the newest closed
    decision bar is older than this, the feed has a gap and we stand down
    rather than trading into the unknown.
    """
    now = now or datetime.now(timezone.utc)
    bars = add_features(resample(minutes, cfg.timeframe))
    if len(bars) < 220:               # EMA200 needs history to be meaningful
        return None

    last_close = bars.index[-1].to_pydatetime()
    age_min = (now - last_close).total_seconds() / 60.0
    if age_min > max_age_min + pd.Timedelta(cfg.timeframe).total_seconds() / 60.0:
        return None

    sigs = lib.trend_pullback(
        bars.iloc[-400:],
        cfg.spec(),
        trade_start=cfg.trade_start_utc_min,
        trade_end=cfg.trade_end_utc_min,
    )
    if not sigs:
        return None

    latest = max(sigs, key=lambda s: s.ts)
    bar_ts = int(bars["ts"].iloc[-1])
    if latest.ts != bar_ts:           # signal is not on the bar that just closed
        return None

    risk_px = abs(latest.entry_px - latest.stop_px)
    if risk_px <= 0:
        return None
    qty = (equity * cfg.risk_per_trade_pct / 100.0) / risk_px

    return Order(
        ts_utc=datetime.fromtimestamp(latest.ts / 1000, timezone.utc).isoformat(),
        side="buy" if latest.side > 0 else "sell",
        entry_type="market",
        entry_px=round(latest.entry_px, 3),
        stop_px=round(latest.stop_px, 3),
        target_px=round(latest.target_px, 3),
        qty=round(qty, 4),
        risk_px=round(risk_px, 3),
        tag=latest.tag,
    )


class DayGuard:
    """Trade-count and daily-loss circuit breaker.

    Keep one instance per trading account.  ``allow`` must return True before
    any order is sent.
    """

    def __init__(self, cfg: LiveConfig):
        self.cfg = cfg
        self._day: str | None = None
        self._count = 0
        self._pnl_r = 0.0

    def _roll(self, now: datetime) -> None:
        key = now.strftime("%Y-%m-%d")
        if key != self._day:
            self._day, self._count, self._pnl_r = key, 0, 0.0

    def allow(self, now: datetime | None = None) -> tuple[bool, str]:
        now = now or datetime.now(timezone.utc)
        self._roll(now)
        if self._count >= self.cfg.max_trades_per_day:
            return False, "daily trade cap reached"
        if self._pnl_r <= -abs(self.cfg.max_daily_loss_r):
            return False, "daily loss limit hit"
        return True, "ok"

    def record_entry(self, now: datetime | None = None) -> None:
        self._roll(now or datetime.now(timezone.utc))
        self._count += 1

    def record_result(self, r_multiple: float, now: datetime | None = None) -> None:
        self._roll(now or datetime.now(timezone.utc))
        self._pnl_r += r_multiple
