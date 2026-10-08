"""Deterministic CCXT adapter tests without network or credentials."""
import unittest
from .ccxt_feed import normalize_ccxt_ticker
from .models import VenueType

class TestCcxtFeed(unittest.TestCase):
    def test_valid_quote(self):
        q=normalize_ccxt_ticker("kraken","BTC/USDT",{
            "bid":100,"ask":101,"bidVolume":5,"askVolume":7,"timestamp":12345})
        self.assertEqual(q.venue_type,VenueType.CEX)
        self.assertEqual(q.venue,"kraken")
        self.assertEqual(q.timestamp_ms,12345)
        self.assertEqual(q.bid_size,5)

    def test_missing_prices_rejected(self):
        self.assertIsNone(normalize_ccxt_ticker("kraken","BTC/USDT",{"bid":100}))
        self.assertIsNone(normalize_ccxt_ticker("kraken","BTC/USDT",{}))

    def test_crossed_or_nonfinite_rejected(self):
        self.assertIsNone(normalize_ccxt_ticker("a","SOL/USDT",{"bid":105,"ask":100}))
        self.assertIsNone(normalize_ccxt_ticker("a","SOL/USDT",{"bid":"nan","ask":100}))

    def test_negative_depth_rejected(self):
        self.assertIsNone(normalize_ccxt_ticker("a","SOL/USDT",{
            "bid":99,"ask":100,"bidVolume":-1}))

if __name__=="__main__":
    unittest.main()
