import unittest
from .costs import CostModel

class CostModelTests(unittest.TestCase):
    def test_percentage_and_fixed_costs(self):
        model = CostModel(
            buy_fee_pct=0.1,
            sell_fee_pct=0.1,
            slippage_pct=0.05,
            price_impact_pct=0.05,
            transfer_cost_usd=0.5,
            network_cost_usd=0.5,
        )
        self.assertAlmostEqual(model.pct_for_size(100), 1.3)
        self.assertAlmostEqual(model.net_pct(2.0, 100), 0.7)

    def test_zero_size_rejected(self):
        with self.assertRaises(ValueError):
            CostModel().pct_for_size(0)

if __name__ == "__main__":
    unittest.main()
