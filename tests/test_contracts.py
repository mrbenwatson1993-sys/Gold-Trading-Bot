import unittest

from tori.contracts import get_contract


class TestContracts(unittest.TestCase):
    def test_point_value_derives_from_tick(self):
        gc = get_contract("GC")
        self.assertEqual(gc.point_value, 100.0)      # $10 per 0.10 tick
        self.assertEqual(get_contract("MGC").point_value, 10.0)
        self.assertEqual(get_contract("ES").point_value, 50.0)

    def test_sizing_respects_the_risk_budget(self):
        mgc = get_contract("MGC")
        # $1000 risk, 12.5 point stop -> $125/contract -> 8 contracts
        self.assertEqual(mgc.contracts_for_risk(1000, 12.5), 8)

    def test_refuses_to_size_when_one_contract_is_too_much(self):
        """The important one: skipping beats silently over-risking."""
        gc = get_contract("GC")          # $1250 risk for a 12.5 point stop
        self.assertEqual(gc.contracts_for_risk(1000, 12.5), 0)

    def test_zero_or_negative_stop_never_sizes(self):
        mgc = get_contract("MGC")
        self.assertEqual(mgc.contracts_for_risk(1000, 0), 0)
        self.assertEqual(mgc.contracts_for_risk(1000, -5), 0)

    def test_pnl_direction(self):
        mgc = get_contract("MGC")
        self.assertAlmostEqual(mgc.pnl(2000, 2010, 1, True), 100.0)
        self.assertAlmostEqual(mgc.pnl(2000, 2010, 1, False), -100.0)
        self.assertAlmostEqual(mgc.pnl(2000, 1990, 2, False), 200.0)

    def test_costs_charge_both_sides(self):
        mgc = get_contract("MGC")
        # 2 contracts: commission 2*2*0.75 = 3.00, slippage 1 tick each way
        self.assertAlmostEqual(mgc.cost(2, 1.0), 3.0 + 2 * 1.0 * 1.0 * 2)

    def test_rounds_to_the_tick_grid(self):
        es = get_contract("ES")
        self.assertAlmostEqual(es.round_to_tick(4321.31), 4321.25)
        self.assertAlmostEqual(es.round_to_tick(4321.40), 4321.50)

    def test_unknown_symbol_is_loud(self):
        with self.assertRaises(KeyError):
            get_contract("NOPE")


if __name__ == "__main__":
    unittest.main()
