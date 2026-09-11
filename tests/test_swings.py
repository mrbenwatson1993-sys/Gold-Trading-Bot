import unittest

from tori.swings import HIGH, LOW, find_swings, last_swing_before, visible_swings
from tests.helpers import zigzag


class TestSwings(unittest.TestCase):
    def setUp(self):
        self.candles = zigzag([(10, 120), (10, 90), (10, 130), (10, 100)])
        self.swings = find_swings(self.candles, strength=3)

    def test_finds_alternating_pivots(self):
        kinds = [s.kind for s in self.swings]
        self.assertIn(HIGH, kinds)
        self.assertIn(LOW, kinds)

    def test_confirmation_lags_by_strength(self):
        for s in self.swings:
            self.assertEqual(s.confirmed_at, s.index + 3)

    def test_visible_swings_hide_the_future(self):
        """The core no-lookahead guarantee: a pivot is invisible until its
        right-hand bars exist."""
        for s in self.swings:
            just_before = visible_swings(self.swings, s.confirmed_at - 1)
            self.assertNotIn(s, just_before)
            self.assertIn(s, visible_swings(self.swings, s.confirmed_at))

    def test_strength_must_be_positive(self):
        with self.assertRaises(ValueError):
            find_swings(self.candles, strength=0)

    def test_last_swing_before(self):
        idx = self.candles.index(self.candles[-1])
        low = last_swing_before(self.swings, idx, LOW)
        self.assertIsNotNone(low)
        self.assertLessEqual(low.index, idx)
        self.assertEqual(low.kind, LOW)

    def test_flat_market_has_no_pivots(self):
        from tests.helpers import flat
        self.assertEqual(find_swings(flat(50), strength=3), [])


if __name__ == "__main__":
    unittest.main()
