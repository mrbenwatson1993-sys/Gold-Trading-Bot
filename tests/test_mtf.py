import unittest

from tori.candles import Candle, atr_series
from tori.config import simple
from tori.mtf import Apex, build_ladder, find_apexes
from tori.trendlines import BEARISH, BULLISH, Trendline
from tests.helpers import BAR, zigzag


def line(kind, anchor_ts, price, slope_per_bar, touches=3):
    t = Trendline(kind=kind, anchor_index=0, anchor_price=price,
                  slope=slope_per_bar, atr_ref=1.0, anchor_ts=anchor_ts,
                  bar_seconds=BAR, timeframe="4h")
    t.touches = [None] * touches      # only the count is read here
    return t


class TestApex(unittest.TestCase):
    def setUp(self):
        self.ts = 1_000_000
        self.cfg = simple().for_timeframe(BAR)
        self.candle = Candle(self.ts, 100, 101, 99, 100)
        # resistance falling from 110, support rising from 90
        self.upper = line(BEARISH, self.ts, 110.0, -0.5)
        self.lower = line(BULLISH, self.ts, 90.0, +0.5)

    def _views(self, lines):
        from tori.mtf import TimeframeView
        return [TimeframeView("4h", BAR, 500, lines, None)]

    def test_detects_a_converging_pair_with_price_inside(self):
        found = find_apexes(self._views([self.upper, self.lower]),
                            self.candle, atr_ref=5.0, cfg=self.cfg)
        self.assertEqual(len(found), 1)
        a = found[0]
        self.assertTrue(a.price_inside)
        self.assertAlmostEqual(a.gap, 20.0)
        self.assertAlmostEqual(a.gap_atr, 4.0)

    def test_apex_time_is_where_the_lines_meet(self):
        a = find_apexes(self._views([self.upper, self.lower]),
                        self.candle, 5.0, self.cfg)[0]
        # gap 20, closing at 1.0 per bar -> 20 bars out
        self.assertAlmostEqual(a.bars_to_apex(BAR), 20.0, places=6)
        self.assertAlmostEqual(self.upper.value_at_ts(a.apex_ts),
                               self.lower.value_at_ts(a.apex_ts), places=6)

    def test_diverging_lines_never_form_an_apex(self):
        widening_up = line(BEARISH, self.ts, 110.0, +0.5)
        widening_down = line(BULLISH, self.ts, 90.0, -0.5)
        self.assertEqual(
            find_apexes(self._views([widening_up, widening_down]),
                        self.candle, 5.0, self.cfg), [])

    def test_price_outside_the_triangle_is_excluded_by_default(self):
        outside = Candle(self.ts, 200, 201, 199, 200)
        self.assertEqual(
            find_apexes(self._views([self.upper, self.lower]), outside,
                        5.0, self.cfg), [])
        self.assertEqual(
            len(find_apexes(self._views([self.upper, self.lower]), outside,
                            5.0, self.cfg, require_inside=False)), 1)

    def test_already_crossed_lines_are_excluded(self):
        crossed_upper = line(BEARISH, self.ts, 80.0, -0.5)   # below support
        self.assertEqual(
            find_apexes(self._views([crossed_upper, self.lower]),
                        self.candle, 5.0, self.cfg), [])

    def test_position_in_range(self):
        a = find_apexes(self._views([self.upper, self.lower]),
                        self.candle, 5.0, self.cfg)[0]
        self.assertAlmostEqual(a.position_in_range, 0.5)   # 100 between 90/110

    def test_very_wide_pairs_are_not_coils(self):
        self.assertEqual(
            find_apexes(self._views([self.upper, self.lower]), self.candle,
                        atr_ref=1.0, cfg=self.cfg, max_gap_atr=6.0), [])


class TestLadder(unittest.TestCase):
    def test_ladder_skips_timeframes_finer_than_the_data(self):
        candles = zigzag([(60, 120), (60, 90), (60, 130), (60, 100)])
        cfg = simple().for_timeframe(BAR)
        views = build_ladder(candles, cfg, len(candles) - 1)
        labels = {v.label for v in views}
        self.assertNotIn("5m", labels)
        self.assertNotIn("15m", labels)
        self.assertNotIn("1h", labels)

    def test_ladder_uses_no_future_bars(self):
        candles = zigzag([(60, 120), (60, 90), (60, 130), (60, 100)])
        cfg = simple().for_timeframe(BAR)
        cut = 150
        a = build_ladder(candles, cfg, cut)
        b = build_ladder(candles[:cut + 1], cfg, cut)
        self.assertEqual([v.bars for v in a], [v.bars for v in b])
        self.assertEqual([len(v.lines) for v in a], [len(v.lines) for v in b])


if __name__ == "__main__":
    unittest.main()
