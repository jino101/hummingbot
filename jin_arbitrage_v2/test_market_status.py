import unittest
from .market_status import MarketStatus, NetworkStatus, compatible_transfer_network

class MarketStatusTests(unittest.TestCase):
    def test_selects_compatible_network(self):
        buy = MarketStatus("buy", "SOL/USDT", True, (
            NetworkStatus("SOL", True, True, 0.2),
            NetworkStatus("ALT", True, True, 0.1),
        ))
        sell = MarketStatus("sell", "SOL/USDT", True, (
            NetworkStatus("SOL", True, False, 0.1),
            NetworkStatus("ALT", True, False, 0.2),
        ))
        route = compatible_transfer_network(buy, sell)
        self.assertIsNotNone(route)
        self.assertEqual(route.network, "SOL")

    def test_unknown_network_fails_closed(self):
        buy = MarketStatus("buy", "SOL/USDT", True, ())
        sell = MarketStatus("sell", "SOL/USDT", True, ())
        self.assertIsNone(compatible_transfer_network(buy, sell))

if __name__ == "__main__":
    unittest.main()
