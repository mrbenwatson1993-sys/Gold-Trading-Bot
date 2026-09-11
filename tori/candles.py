"""Candle series: loading, resampling and ATR.

ATR is deliberately the only derived series in the project. It is never a
signal -- it exists so that tolerances ("how close is a touch?", "how far did
the break displace?") scale with the instrument and with volatility instead of
being hard-coded in points.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

# Common bar sizes, in seconds.
TIMEFRAMES = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200,
    "1d": 86400, "1w": 604800,
}


@dataclass(frozen=True)
class Candle:
    ts: int          # bar OPEN time, unix seconds, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def body_ratio(self) -> float:
        """Body as a fraction of the full range. 1.0 = marubozu, 0.0 = doji."""
        r = self.range
        return self.body / r if r > 0 else 0.0

    @property
    def is_up(self) -> bool:
        return self.close >= self.open

    def __str__(self) -> str:
        return (f"{self.dt:%Y-%m-%d %H:%M} O{self.open:.2f} H{self.high:.2f} "
                f"L{self.low:.2f} C{self.close:.2f}")


def load_csv(path: str) -> list[Candle]:
    """Read OHLC candles from CSV.

    Tolerant of the usual exports (TradingView, broker downloads, Gate/Kraken
    dumps): column names are matched case-insensitively and the time column may
    be a unix timestamp or an ISO-8601 string.
    """
    out: list[Candle] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: empty or headerless CSV")
        cols = {name.strip().lower(): name for name in reader.fieldnames}

        def pick(*names: str) -> str:
            for n in names:
                if n in cols:
                    return cols[n]
            raise ValueError(f"{path}: need one of {names}; got {reader.fieldnames}")

        tcol = pick("time", "timestamp", "date", "datetime", "ts", "open time")
        ocol, hcol = pick("open", "o"), pick("high", "h")
        lcol, ccol = pick("low", "l"), pick("close", "c")
        vcol = cols.get("volume") or cols.get("vol") or cols.get("v")

        for row in reader:
            raw = (row[tcol] or "").strip()
            if not raw:
                continue
            out.append(Candle(
                ts=_parse_time(raw),
                open=float(row[ocol]), high=float(row[hcol]),
                low=float(row[lcol]), close=float(row[ccol]),
                volume=float(row[vcol]) if vcol and row.get(vcol) else 0.0,
            ))
    out.sort(key=lambda c: c.ts)
    return _dedupe(out)


def _parse_time(raw: str) -> int:
    try:
        val = float(raw)
    except ValueError:
        pass
    else:
        # Milliseconds if it is implausibly large for seconds.
        return int(val / 1000) if val > 1e11 else int(val)
    text = raw.replace("Z", "+00:00").replace("/", "-")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                    "%d-%m-%Y %H:%M", "%m-%d-%Y"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"unparseable timestamp {raw!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _dedupe(candles: list[Candle]) -> list[Candle]:
    """Drop repeated timestamps, keeping the last occurrence."""
    seen: dict[int, Candle] = {}
    for c in candles:
        seen[c.ts] = c
    return [seen[k] for k in sorted(seen)]


def save_csv(candles: list[Candle], path: str) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.ts, f"{c.open:.6f}", f"{c.high:.6f}",
                        f"{c.low:.6f}", f"{c.close:.6f}", f"{c.volume:.4f}"])


def bar_seconds(candles: list[Candle]) -> int:
    """Infer the bar size from the series (median gap, robust to weekend gaps)."""
    if len(candles) < 3:
        return 0
    gaps = [b.ts - a.ts for a, b in zip(candles, candles[1:]) if b.ts > a.ts]
    return int(statistics.median(gaps)) if gaps else 0


def timeframe_name(seconds: int) -> str:
    for name, secs in TIMEFRAMES.items():
        if secs == seconds:
            return name
    return f"{seconds}s"


def resample(candles: list[Candle], seconds: int) -> list[Candle]:
    """Aggregate to a higher timeframe. Used for the top-down (HTF) read."""
    if seconds <= 0:
        raise ValueError("resample period must be positive")
    buckets: dict[int, list[Candle]] = {}
    for c in candles:
        buckets.setdefault(c.ts - (c.ts % seconds), []).append(c)
    out: list[Candle] = []
    for start in sorted(buckets):
        group = buckets[start]
        out.append(Candle(
            ts=start,
            open=group[0].open,
            high=max(g.high for g in group),
            low=min(g.low for g in group),
            close=group[-1].close,
            volume=sum(g.volume for g in group),
        ))
    return out


def atr_series(candles: list[Candle], period: int = 14) -> list[float]:
    """Wilder's ATR, aligned index-for-index with `candles`.

    Values before the period is filled use the running average of available
    true ranges so that early bars are usable rather than zero.
    """
    if not candles:
        return []
    trs: list[float] = [candles[0].range]
    for prev, cur in zip(candles, candles[1:]):
        trs.append(max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        ))
    out: list[float] = []
    running = 0.0
    for i, tr in enumerate(trs):
        if i < period:
            running += tr
            out.append(running / (i + 1))
        else:
            out.append((out[-1] * (period - 1) + tr) / period)
    return out
