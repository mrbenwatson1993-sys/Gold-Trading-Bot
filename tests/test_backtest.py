import os
import unittest

from tori.backtest import run
from tori.candles import bar_seconds, load_csv
from tori.config import RiskConfig, simple
from tests.helpers import flat
from tests.test_strategy import reversal_chart
from tests.helpers import BAR

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "gold_4h.csv")


class TestBacktest(unittest.TestCase):
    def setUp(self):
        self.cfg = simple().for_timeframe(BAR)
        self.cfg.min_age_bars = 20
        self.risk = RiskConfig(symbol="MGC", starting_equity=250_000)

    def test_flat_market_trades_nothing(self):
        result = run(flat(500), self.cfg, self.risk)
        self.assertEqual(result.trades, [])
        self.assertEqual(result.stats["trades"], 0)

    def test_equity_curve_matches_trade_pnl(self):
        result = run(reversal_chart(), self.cfg, self.risk)
        equity = self.risk.starting_equity
        for t in result.trades:
            equity += t.net
            self.assertAlmostEqual(t.equity_after, equity, places=6)

    def test_costs_are_always_charged(self):
        result = run(reversal_chart(), self.cfg, self.risk)
        for t in result.trades:
            self.assertGreater(t.costs, 0)
            self.assertAlmostEqual(t.net, t.gross - t.costs, places=6)

    def test_losses_are_bounded_near_one_r(self):
        """The resting stop exists precisely so a loss cannot run away."""
        result = run(reversal_chart(), self.cfg, self.risk)
        for t in result.trades:
            self.assertGreater(t.r_multiple, -2.0, f"runaway loss: {t.r_multiple}")

    def test_only_one_position_at_a_time(self):
        result = run(reversal_chart(), self.cfg, self.risk)
        for a, b in zip(result.trades, result.trades[1:]):
            self.assertLessEqual(a.exit_index, b.entry_index)


@unittest.skipUnless(os.path.exists(DATA), "no market data downloaded")
class TestOnRealData(unittest.TestCase):
    """The synthetic charts are clean by construction. Real gold is not."""

    @classmethod
    def setUpClass(cls):
        cls.candles = load_csv(DATA)
        cls.cfg = simple().for_timeframe(bar_seconds(cls.candles))
        cls.risk = RiskConfig(symbol="MGC", starting_equity=250_000)

    def test_runs_and_trades(self):
        result = run(self.candles, self.cfg, self.risk)
        self.assertGreater(len(result.trades), 20)

    def test_no_loss_exceeds_the_risk_budget_by_much(self):
        result = run(self.candles, self.cfg, self.risk)
        for t in result.trades:
            self.assertGreater(t.r_multiple, -3.0,
                               f"loss of {t.r_multiple:.2f}R on {t.entry_ts}")

    def test_truncating_real_history_cannot_change_settled_trades(self):
        cut = len(self.candles) - 300
        short = run(self.candles[:cut], self.cfg, self.risk)
        full = run(self.candles, self.cfg, self.risk)
        settled = [t for t in short.trades
                   if t.exit_index < cut - 1 and t.exit_reason != "open at end"]
        self.assertGreater(len(settled), 10)
        for a, b in zip(settled, full.trades):
            self.assertEqual(a.entry_index, b.entry_index)
            self.assertEqual(a.exit_index, b.exit_index)
            self.assertAlmostEqual(a.exit_price, b.exit_price, places=6)


if __name__ == "__main__":
    unittest.main()
