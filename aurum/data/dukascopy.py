"""Dukascopy tick downloader -> 1-minute bars with real bid/ask spread.

Dukascopy publishes free historical tick data as hourly LZMA-compressed
``.bi5`` files.  Each file is a flat array of 20-byte big-endian records:

    uint32  milliseconds offset from the start of the hour (UTC)
    uint32  ask price in points
    uint32  bid price in points
    float32 ask volume
    float32 bid volume

For XAUUSD the point divisor is 1000 (3 decimal places).

We keep 1-minute bars rather than the raw ticks: 1m is fine enough to
resolve which of a stop or a target was touched first inside a 5m or 15m
signal bar -- the single biggest source of dishonesty in bar-level
backtests -- while being ~200x smaller than tick data.

Crucially we also retain the *real historical spread* per minute.  Gold
spreads widen enormously outside the London/NY window and during news, and
a backtest that assumes a flat spread will invent an edge that does not
exist.
"""

from __future__ import annotations

import calendar
import datetime as dt
import io
import lzma
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://datafeed.dukascopy.com/datafeed"
RECORD = struct.Struct(">3I2f")
POINT_DIVISOR = {"XAUUSD": 1000.0, "XAGUSD": 1000.0, "EURUSD": 100000.0}

_print_lock = threading.Lock()


def _hour_url(symbol: str, when: dt.datetime) -> str:
    # Dukascopy months are 0-indexed in the path.
    return (
        f"{BASE}/{symbol}/{when.year:04d}/{when.month - 1:02d}/{when.day:02d}"
        f"/{when.hour:02d}h_ticks.bi5"
    )


_tls = threading.local()


def _session() -> requests.Session:
    """One keep-alive session per thread.

    The sandbox egress proxy drops tunnels that are opened and closed rapidly,
    so a fresh TLS connection per file fails roughly half the time.  Reusing a
    connection per worker turns tens of thousands of tunnel setups into a
    handful and takes the success rate to ~100%.
    """
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=4,
            pool_maxsize=4,
            max_retries=Retry(
                total=5,
                backoff_factor=0.8,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"],
            ),
        )
        s.mount("https://", adapter)
        s.headers["User-Agent"] = "Mozilla/5.0"
        _tls.s = s
    return s


def _fetch(url: str, timeout: int = 45) -> bytes | None:
    """Return raw bi5 bytes, or None when the hour has no data."""
    for attempt in range(3):
        try:
            resp = _session().get(url, timeout=timeout)
            if resp.status_code == 404:
                return None  # market closed / no data for this hour
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass
        time.sleep(1.0 + attempt)
    return None


def _decode(raw: bytes, hour_start_ms: int, divisor: float) -> np.ndarray | None:
    """Decode one hour of ticks into a structured array."""
    if not raw:
        return None
    try:
        data = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO).decompress(raw)
    except lzma.LZMAError:
        return None
    n = len(data) // RECORD.size
    if n == 0:
        return None

    buf = np.frombuffer(data[: n * RECORD.size], dtype=">u4").reshape(n, 5)
    ms = buf[:, 0].astype(np.int64)
    ask = buf[:, 1].astype(np.float64) / divisor
    bid = buf[:, 2].astype(np.float64) / divisor

    out = np.empty(n, dtype=[("ts", "i8"), ("bid", "f8"), ("ask", "f8")])
    out["ts"] = hour_start_ms + ms
    out["bid"] = bid
    out["ask"] = ask
    # Dukascopy occasionally emits crossed/zero quotes at session edges.
    valid = (bid > 0) & (ask > 0) & (ask >= bid)
    return out[valid] if valid.any() else None


def _to_minute_bars(ticks: np.ndarray) -> pd.DataFrame:
    """Aggregate ticks to 1-minute OHLC on the mid plus spread statistics."""
    mid = (ticks["bid"] + ticks["ask"]) / 2.0
    spread = ticks["ask"] - ticks["bid"]
    minute = ticks["ts"] // 60_000

    df = pd.DataFrame({"minute": minute, "mid": mid, "spread": spread})
    g = df.groupby("minute", sort=True)
    bars = g.agg(
        open=("mid", "first"),
        high=("mid", "max"),
        low=("mid", "min"),
        close=("mid", "last"),
        spread_mean=("spread", "mean"),
        spread_med=("spread", "median"),
        ticks=("mid", "size"),
    ).reset_index()
    bars["ts"] = bars["minute"] * 60_000
    return bars.drop(columns=["minute"])


def download_range(
    symbol: str,
    start: dt.date,
    end: dt.date,
    out_dir: Path,
    workers: int = 6,
    shard: int = 0,
    shards: int = 1,
) -> None:
    """Download [start, end) hour by hour, writing one parquet per month.

    Months are sharded round-robin so several processes can run concurrently
    without colliding.  Each process keeps its own small keep-alive pool; the
    egress proxy tolerates a handful of long-lived tunnels far better than many
    short ones.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    divisor = POINT_DIVISOR[symbol]

    months: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    months = [mo for i, mo in enumerate(months) if i % shards == shard]

    for year, month in months:
        target = out_dir / f"{symbol}_{year:04d}{month:02d}.parquet"
        if target.exists():
            with _print_lock:
                print(f"[skip] {target.name}", flush=True)
            continue

        days = calendar.monthrange(year, month)[1]
        hours: list[dt.datetime] = []
        for day in range(1, days + 1):
            d = dt.date(year, month, day)
            if not (start <= d < end):
                continue
            # Forex/metals week: Sunday ~21:00 UTC to Friday ~21:00 UTC.
            wd = d.weekday()  # Mon=0 .. Sun=6
            if wd == 5:  # Saturday: always closed
                continue
            for hour in range(24):
                if wd == 6 and hour < 20:  # Sunday morning
                    continue
                if wd == 4 and hour > 21:  # late Friday
                    continue
                hours.append(dt.datetime(year, month, day, hour, tzinfo=dt.timezone.utc))

        if not hours:
            continue

        frames: list[pd.DataFrame] = []
        done = 0

        def work(when: dt.datetime):
            raw = _fetch(_hour_url(symbol, when))
            if raw is None:
                return None
            hour_ms = int(when.timestamp() * 1000)
            ticks = _decode(raw, hour_ms, divisor)
            if ticks is None:
                return None
            return _to_minute_bars(ticks)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for frame in pool.map(work, hours):
                done += 1
                if frame is not None and len(frame):
                    frames.append(frame)
                if done % 120 == 0:
                    with _print_lock:
                        print(
                            f"  {year}-{month:02d}: {done}/{len(hours)} hours",
                            flush=True,
                        )

        if not frames:
            with _print_lock:
                print(f"[empty] {year}-{month:02d}", flush=True)
            continue

        month_df = (
            pd.concat(frames, ignore_index=True)
            .sort_values("ts")
            .drop_duplicates("ts", keep="last")
            .reset_index(drop=True)
        )
        month_df.to_parquet(target, index=False, compression="zstd")
        with _print_lock:
            print(
                f"[ok] {target.name}  bars={len(month_df):,}  "
                f"median_spread={month_df.spread_med.median():.3f}",
                flush=True,
            )


def load_minutes(bars_dir: Path, symbol: str = "XAUUSD") -> pd.DataFrame:
    """Load every monthly parquet into one tz-aware 1-minute frame."""
    files = sorted(bars_dir.glob(f"{symbol}_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet files in {bars_dir}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("dt")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2026-09-01")
    ap.add_argument("--out", default="data/bars")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    a = ap.parse_args()

    download_range(
        a.symbol,
        dt.date.fromisoformat(a.start),
        dt.date.fromisoformat(a.end),
        Path(a.out),
        workers=a.workers,
        shard=a.shard,
        shards=a.shards,
    )
