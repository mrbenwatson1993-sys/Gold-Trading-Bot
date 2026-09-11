import os
import tempfile
import unittest

from tori.candles import (atr_series, bar_seconds, load_csv, resample,
                          save_csv, timeframe_name)
from tests.helpers import BAR, candle, flat


class TestCandles(unittest.TestCase):
    def test_csv_round_trip(self):
        original = flat(20, 1950.0)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.csv")
            save_csv(original, path)
            loaded = load_csv(path)
        self.assertEqual(len(loaded), len(original))
        self.assertEqual(loaded[0].ts, original[0].ts)
        self.assertAlmostEqual(loaded[5].close, original[5].close, places=6)

    def test_csv_accepts_iso_timestamps_and_odd_headers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tv.csv")
            with open(path, "w") as fh:
                fh.write("Date,Open,High,Low,Close\n")
                fh.write("2024-05-06 04:00:00,2320,2330,2315,2325\n")
                fh.write("2024-05-06T08:00:00Z,2325,2340,2320,2338\n")
            loaded = load_csv(path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[1].ts - loaded[0].ts, BAR)
        self.assertEqual(loaded[1].close, 2338)

    def test_duplicate_timestamps_collapse(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dup.csv")
            with open(path, "w") as fh:
                fh.write("time,open,high,low,close\n")
                fh.write("100,1,2,0,1\n100,1,2,0,9\n200,1,2,0,2\n")
            loaded = load_csv(path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].close, 9)   # last one wins

    def test_bar_seconds_survives_gaps(self):
        candles = flat(30)
        # drop a weekend-sized hole in the middle
        candles = candles[:10] + [
            candle(40 + i, 100, 100.5, 99.5, 100) for i in range(10)]
        self.assertEqual(bar_seconds(candles), BAR)
        self.assertEqual(timeframe_name(BAR), "4h")

    def test_resample_aggregates_ohlc(self):
        candles = [candle(i, 100 + i, 105 + i, 95 + i, 101 + i) for i in range(12)]
        daily = resample(candles, 86400)     # six 4h bars per day
        self.assertEqual(len(daily), 2)
        self.assertEqual(daily[0].open, candles[0].open)
        self.assertEqual(daily[0].close, candles[5].close)
        self.assertEqual(daily[0].high, max(c.high for c in candles[:6]))
        self.assertEqual(daily[0].low, min(c.low for c in candles[:6]))

    def test_atr_is_positive_and_aligned(self):
        candles = flat(50)
        atr = atr_series(candles, 14)
        self.assertEqual(len(atr), len(candles))
        self.assertTrue(all(a > 0 for a in atr))

    def test_body_ratio(self):
        doji = candle(0, 100, 102, 98, 100)
        marubozu = candle(1, 98, 102, 98, 102)
        self.assertAlmostEqual(doji.body_ratio, 0.0)
        self.assertAlmostEqual(marubozu.body_ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
