import unittest

from tori.candles import atr_series
from tori.config import StrategyConfig, simple
from tori.swings import find_swings
from tori.trendlines import BEARISH, BULLISH, build_trendlines
from tests.helpers import BAR, zigzag


def descending_chart():
    """Three lower highs, then a break upward through the line."""
    return zigzag([
        (12, 120),   # high 1
        (12, 96),
        (12, 114),   # high 2  (lower)
        (12, 92),
        (12, 108),   # high 3  (lower still)
        (12, 88),
        (14, 125),   # drives up through the line
    ])


class TestTrendlines(unittest.TestCase):
    def setUp(self):
        self.cfg = simple().for_timeframe(BAR)
        self.cfg.min_age_bars = 20
        self.cfg.min_touch_gap_bars = 6

    def _lines(self, candles, as_of=None, through=None):
        swings = find_swings(candles, self.cfg.swing_strength)
        atr = atr_series(candles, self.cfg.atr_period)
        i = len(candles) - 1 if as_of is None else as_of
        return build_trendlines(candles, swings, atr, self.cfg, i,
                                intact_through=through)

    def test_finds_a_descending_line_across_lower_highs(self):
        candles = descending_chart()
        # look just before the break, so the line is still intact
        lines = self._lines(candles, as_of=70)
        bearish = [l for l in lines if l.kind == BEARISH]
        self.assertTrue(bearish, "expected a descending resistance line")
        self.assertGreaterEqual(max(l.touch_count for l in bearish), 2)
        self.assertTrue(all(l.slope < 0 for l in bearish))

    def test_line_dies_once_price_closes_through_it(self):
        candles = descending_chart()
        before = [l for l in self._lines(candles, as_of=70) if l.kind == BEARISH]
        after = [l for l in self._lines(candles) if l.kind == BEARISH]
        self.assertTrue(before)
        # after the rally every one of those lines has been closed through
        self.assertEqual(len(after), 0)

    def test_intact_through_lets_the_breaking_bar_be_excluded(self):
        """A break must not disqualify the line it is breaking."""
        candles = descending_chart()
        i = len(candles) - 1
        strict = self._lines(candles, as_of=i)
        lenient = self._lines(candles, as_of=i, through=40)
        self.assertGreaterEqual(len(lenient), len(strict))

    def test_ascending_line_across_higher_lows(self):
        # three collinear higher lows at 90 / 96 / 102
        candles = zigzag([(12, 90), (12, 112), (12, 96), (12, 124),
                          (12, 102), (12, 136)])
        lines = self._lines(candles)
        bullish = [l for l in lines if l.kind == BULLISH]
        self.assertTrue(bullish, "expected an ascending support line")
        self.assertTrue(all(l.slope > 0 for l in bullish))

    def test_too_young_lines_are_rejected(self):
        candles = descending_chart()
        self.cfg.min_age_bars = 500
        self.assertEqual(self._lines(candles, as_of=70), [])

    def test_touches_must_be_spaced_out(self):
        candles = descending_chart()
        self.cfg.min_touch_gap_bars = 200
        self.assertEqual(self._lines(candles, as_of=70), [])

    def test_flat_market_yields_no_lines(self):
        from tests.helpers import flat
        self.assertEqual(self._lines(flat(200)), [])

    def test_time_projection_matches_index_projection(self):
        """A line must evaluate identically whether addressed by bar index or
        by timestamp -- this is what lets a weekly line be read on a 5m chart."""
        candles = descending_chart()
        lines = self._lines(candles, as_of=70)
        self.assertTrue(lines)
        for line in lines:
            for i in (30, 50, 70):
                self.assertAlmostEqual(line.value_at(i),
                                       line.value_at_ts(candles[i].ts), places=6)

    def test_line_extends_indefinitely_past_its_last_touch(self):
        candles = descending_chart()
        line = self._lines(candles, as_of=70)[0]
        far = line.value_at(10_000)
        self.assertLess(far, line.value_at(70))   # descending, still descending


if __name__ == "__main__":
    unittest.main()
