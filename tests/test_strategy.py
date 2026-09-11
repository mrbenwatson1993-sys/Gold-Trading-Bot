import unittest

from tori.candles import atr_series
from tori.config import RiskConfig, simple
from tori.backtest import run
from tori.strategy import ToriStrategy
from tests.helpers import BAR, zigzag
from tests.test_trendlines import descending_chart


def reversal_chart():
    """A downtrend of lower highs, a break up, then a staircase of higher
    lows -- enough structure for a Safety Line to form and later be broken."""
    return zigzag([
        (12, 120), (12, 96), (12, 114), (12, 92), (12, 108), (12, 88),
        (14, 126),              # the break
        (10, 116), (12, 140),   # higher low, new high
        (10, 128), (12, 152),   # higher low, new high
        (20, 104),              # structure breaks down -> exit
    ])


class TestStrategy(unittest.TestCase):
    def setUp(self):
        self.cfg = simple().for_timeframe(BAR)
        self.cfg.min_age_bars = 20
        self.candles = reversal_chart()
        self.atr = atr_series(self.candles, self.cfg.atr_period)
        self.strat = ToriStrategy(self.candles, self.atr, self.cfg)

    def _first_signal(self):
        for i in range(30, len(self.candles) - 1):
            sig = self.strat.find_signal(i)
            if sig is not None:
                return i, sig
            self.strat.observe(i)
        return None, None

    def test_produces_a_long_on_the_break_of_a_descending_line(self):
        i, sig = self._first_signal()
        self.assertIsNotNone(sig, "expected a break signal")
        self.assertEqual(sig.direction, "long")
        self.assertEqual(sig.brk.line.kind, "bearish")

    def test_entry_fills_on_the_next_bar_open(self):
        i, sig = self._first_signal()
        self.assertEqual(sig.entry_index, i + 1)
        self.assertEqual(sig.entry_price, self.candles[i + 1].open)

    def test_initial_stop_sits_below_entry_for_a_long(self):
        _, sig = self._first_signal()
        self.assertLess(sig.initial_stop, sig.entry_price)
        self.assertGreater(sig.risk, 0)

    def test_safety_line_anchors_at_the_breakout_low(self):
        """It must pin to where the new trend began, not creep up to the last
        two swings -- a re-anchored line gets steeper and cuts winners off."""
        i, sig = self._first_signal()
        pos = self.strat.open_position(sig, contracts=1)
        self.assertIsNotNone(pos.safety_origin)
        for j in range(pos.entry_index, len(self.candles)):
            if self.strat.check_exit(pos, j) is not None:
                break
        self.assertIsNotNone(pos.safety_line, "a Safety Line should have formed")
        self.assertEqual(pos.safety_line.anchor_index, pos.safety_origin.index)
        self.assertGreater(pos.safety_line.slope, 0)   # rising under a long

    def test_position_exits_and_does_so_structurally(self):
        i, sig = self._first_signal()
        pos = self.strat.open_position(sig, contracts=1)
        outcome = None
        for j in range(pos.entry_index, len(self.candles)):
            outcome = self.strat.check_exit(pos, j)
            if outcome is not None:
                break
        self.assertIsNotNone(outcome, "the trade should have closed")
        self.assertIn(outcome[1], ("safety line", "hard stop", "failed break"))

    def test_no_profit_target_exists_anywhere(self):
        """There is no fixed RR. Only 'safety line', 'failed break' and
        'hard stop' may ever end a trade."""
        result = run(self.candles, self.cfg,
                     RiskConfig(symbol="MGC", starting_equity=250_000))
        reasons = {t.exit_reason for t in result.trades}
        self.assertTrue(reasons <= {"safety line", "hard stop", "failed break",
                                    "open at end"}, reasons)


class TestNoLookahead(unittest.TestCase):
    def test_truncating_the_future_cannot_change_the_past(self):
        """The strongest guarantee in the project.

        Run the backtest on the first N bars, then on every bar. The trades
        from the short run must be a prefix of the long run: if any decision
        peeked at a future bar, the two would disagree.
        """
        candles = reversal_chart()
        cfg = simple().for_timeframe(BAR)
        cfg.min_age_bars = 20
        risk = RiskConfig(symbol="MGC", starting_equity=250_000)

        cut = len(candles) - 25
        short = run(candles[:cut], cfg, risk)
        full = run(candles, cfg, risk)

        # compare only trades that had fully closed before the cut
        settled = [t for t in short.trades
                   if t.exit_index < cut - 1 and t.exit_reason != "open at end"]
        self.assertTrue(settled or not full.trades,
                        "test needs at least one settled trade to be meaningful")
        for a, b in zip(settled, full.trades):
            self.assertEqual(a.entry_index, b.entry_index)
            self.assertEqual(a.exit_index, b.exit_index)
            self.assertAlmostEqual(a.entry_price, b.entry_price, places=6)
            self.assertAlmostEqual(a.exit_price, b.exit_price, places=6)


if __name__ == "__main__":
    unittest.main()
