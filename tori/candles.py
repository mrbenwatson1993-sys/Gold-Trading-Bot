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
    # utf-8-sig strips the byte-order mark spreadsheet exports leave behind,
    # which otherwise turns the first column name into "\ufeffDate".
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: empty or headerless CSV")
        cols = {name.strip().strip('"').lstrip("\ufeff").lower(): name
                for name in reader.fieldnames}

        def pick(*names: str) -> str:
            for n in names:
                if n in cols:
                    return cols[n]
            raise ValueError(f"{path}: need one of {names}; got {reader.fieldnames}")

        tcol = pick("time", "timestamp", "date", "datetime", "ts", "open time")
        ocol, hcol = pick("open", "o"), pick("high", "h")
        # "price" is what investing.com-style exports call the close.
        lcol, ccol = pick("low", "l"), pick("close", "c", "price", "last")
        vcol = cols.get("volume") or cols.get("vol") or cols.get("v")

        for row in reader:
            raw = (row[tcol] or "").strip()
            if not raw:
                continue
            out.append(Candle(
                ts=_parse_time(raw),
                open=_num(row[ocol]), high=_num(row[hcol]),
                low=_num(row[lcol]), close=_num(row[ccol]),
                volume=_volume(row[vcol]) if vcol and row.get(vcol) else 0.0,
            ))
    out.sort(key=lambda c: c.ts)
    return _dedupe(out)


def _num(raw: str) -> float:
    """Parse a price from a real-world export.

    Broker and investing.com downloads wrap numbers in quotes and put
    thousands separators in them, so "1,229.80" has to survive the trip.
    """
    return float(str(raw).strip().replace(",", "").replace('"', "").replace("$", ""))


def _volume(raw: str) -> float:
    """Volume is often abbreviated: 199.65K, 1.2M."""
    text = str(raw).strip().replace(",", "").replace('"', "").upper()
    if not text or text == "-":
        return 0.0
    mult = {"K": 1e3, "M": 1e6, "B": 1e9}.get(text[-1:])
    try:
        return float(text[:-1]) * mult if mult else float(text)
    except ValueError:
        return 0.0


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
        text = raw.replace("Z", "+00:00").strip().strip('"')
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                    "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%m/%d/%Y",
                    "%d/%m/%Y", "%d-%m-%Y %H:%M", "%m-%d-%Y"):
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


def validate(candles: list[Candle], repair: bool = True) -> tuple[list[Candle], dict]:
    """Check OHLC integrity, and optionally repair what can be repaired.

    Real exports are frequently inconsistent: the close sits outside the bar's
    own high-low range, usually because the close column and the OHLC columns
    were sourced differently (a settlement price against session prices, say).
    That matters here more than in most strategies, because every trendline is
    drawn through highs and lows and every entry is a close crossing one.

    The repair widens the range to contain the open and close, which is the
    weakest assumption available: the true high was at least the close. It
    cannot invent the real extreme, so the report always states how many bars
    were touched and by how much -- if that number is large, the data is not
    fit for this strategy and no amount of repair changes it.
    """
    fixed: list[Candle] = []
    broken = 0
    total_shift = 0.0
    worst = 0.0
    for c in candles:
        hi = max(c.high, c.open, c.close)
        lo = min(c.low, c.open, c.close)
        if hi != c.high or lo != c.low:
            broken += 1
            shift = (hi - c.high) + (c.low - lo)
            total_shift += shift
            worst = max(worst, shift)
        fixed.append(Candle(c.ts, c.open, hi, lo, c.close, c.volume)
                     if repair else c)
    atrs = atr_series(candles, 14)
    mean_atr = sum(atrs) / len(atrs) if atrs else 0.0
    report = {
        "bars": len(candles),
        "inconsistent": broken,
        "pct": broken / len(candles) * 100 if candles else 0.0,
        "mean_shift": total_shift / broken if broken else 0.0,
        "worst_shift": worst,
        "mean_atr": mean_atr,
        "shift_in_atr": (total_shift / broken / mean_atr) if broken and mean_atr else 0.0,
    }
    return (fixed if repair else candles), report


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
