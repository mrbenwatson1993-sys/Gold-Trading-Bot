"""Synthetic candle builders, so tests assert on structure we control."""

from __future__ import annotations

from tori.candles import Candle

BAR = 14400


def candle(i: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(ts=i * BAR, open=o, high=h, low=l, close=c, volume=1.0)


def flat(n: int, price: float = 100.0, start: int = 0) -> list[Candle]:
    return [candle(start + i, price, price + 0.5, price - 0.5, price)
            for i in range(n)]


def zigzag(legs: list[tuple[int, float]], start_price: float = 100.0) -> list[Candle]:
    """Build candles that walk linearly to each (bars, target_price) leg.

    Produces clean, unambiguous swing points, which is what the trendline
    tests need to assert exact touch counts.
    """
    out: list[Candle] = []
    price = start_price
    i = 0
    for bars, target in legs:
        step = (target - price) / bars
        for _ in range(bars):
            nxt = price + step
            hi, lo = max(price, nxt), min(price, nxt)
            out.append(candle(i, price, hi + 0.3, lo - 0.3, nxt))
            price = nxt
            i += 1
    return out
