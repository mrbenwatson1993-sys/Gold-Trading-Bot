"""Data acquisition.

Gold *futures* (GC) history is what this strategy is ultimately for, but CME
and the usual free futures feeds are not reachable from every environment, and
none of them give deep intraday history for free. So there are two paths:

  * `import_csv`  -- the real one. Export 4H GC/MGC candles from your broker or
    TradingView and point the engine at the file.
  * `fetch_gate`  -- development data. PAXG/USDT is tokenised spot gold and
    tracks the metal closely, so it exercises the engine against genuine gold
    price action rather than synthetic noise. It is a stand-in for building and
    validating the logic, not a substitute for backtesting your actual
    contract: no settlement, no roll, no pit session, crypto-hours liquidity.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .candles import Candle, save_csv

GATE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
MAX_POINTS_PER_REQUEST = 999


def fetch_gate(pair: str = "PAXG_USDT", interval: str = "4h",
               bars: int = 9000, verbose: bool = True) -> list[Candle]:
    """Page backwards through Gate's candlestick endpoint.

    The API caps a single request at 1000 points and refuses anything more than
    10000 points ago, so deep history is assembled from consecutive windows.
    """
    step = _interval_seconds(interval)
    now = int(time.time()) // step * step
    bars = min(bars, 9900)          # server-side "points ago" ceiling

    collected: dict[int, Candle] = {}
    end = now
    remaining = bars
    while remaining > 0:
        count = min(MAX_POINTS_PER_REQUEST, remaining)
        start = end - count * step
        rows = _gate_request(pair, interval, start, end)
        if not rows:
            break
        for row in rows:
            # [ts, quote_volume, close, high, low, open, base_volume, closed]
            ts = int(row[0])
            collected[ts] = Candle(
                ts=ts, open=float(row[5]), high=float(row[3]),
                low=float(row[4]), close=float(row[2]), volume=float(row[6]),
            )
        if verbose:
            print(f"  fetched {len(rows):>4} bars, {len(collected)} total", flush=True)
        end = start - step
        remaining -= count
        time.sleep(0.25)            # be polite to a free endpoint

    out = [collected[k] for k in sorted(collected)]
    # The most recent bar is still forming; a half-built candle would fake
    # breaks that have not happened yet.
    return out[:-1] if out else out


def _gate_request(pair: str, interval: str, start: int, end: int) -> list:
    url = (f"{GATE_URL}?currency_pair={pair}&interval={interval}"
           f"&from={start}&to={end}")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == 3:
                raise RuntimeError(f"gate.io request failed: {exc}") from exc
            time.sleep(2 ** attempt)
    return []


def _interval_seconds(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    return value * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="download development candles")
    p.add_argument("--pair", default="PAXG_USDT")
    p.add_argument("--interval", default="4h")
    p.add_argument("--bars", type=int, default=9000)
    p.add_argument("--out", default="data/gold_4h.csv")
    args = p.parse_args(argv)

    print(f"fetching {args.bars} x {args.interval} {args.pair} ...")
    candles = fetch_gate(args.pair, args.interval, args.bars)
    if not candles:
        print("no data returned")
        return 1
    save_csv(candles, args.out)
    print(f"wrote {len(candles)} candles -> {args.out}")
    print(f"  {candles[0].dt:%Y-%m-%d} .. {candles[-1].dt:%Y-%m-%d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
