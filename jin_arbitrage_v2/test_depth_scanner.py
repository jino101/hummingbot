"""Network-free tests for depth-aware paper scanning."""
import unittest
from .depth_scanner import normalize_book, buy_base_with_usd, sell_base_for_quote, scan_depth_books

class TestDepthScanner(unittest.TestCase):
    def book(self, venue, bid, ask, qty=10, timestamp=1000):
        return normalize_book(venue, "SOL/USDT",
                              {"bids":[[bid,qty]],"asks":[[ask,qty]]},
                              observed_ms=timestamp, fee_pct=0.1)

    def test_orderbook_normalization(self):
        book=normalize_book("x","SOL/USDT",
                            {"bids":[[98,1],[99,2]],"asks":[[102,1],[101,2]]},
                            observed_ms=1000)
        self.assertEqual(book.bids[0][0],99)
        self.assertEqual(book.asks[0][0],101)

    def test_depth_walk(self):
        self.assertAlmostEqual(buy_base_with_usd([(10,1),(20,1)],20),1.5)
        self.assertEqual(buy_base_with_usd([(10,1)],20),0)
        self.assertAlmostEqual(sell_base_for_quote([(20,1),(10,1)],1.5),25)
        self.assertEqual(sell_base_for_quote([(20,1)],1.5),0)

    def test_paper_candidate(self):
        out=scan_depth_books([self.book("a",99,100),self.book("b",103,104)],
                             size_usd=100,min_net_pct=0.35,now_ms=1000)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["buy"],"a")
        self.assertAlmostEqual(out[0]["estimated_net_pct"],2.65)

    def test_partial_depth_rejected(self):
        out=scan_depth_books([self.book("a",99,100,qty=.1),
                              self.book("b",103,104)],
                             size_usd=100,now_ms=1000)
        self.assertEqual(out,[])

    def test_stale_rejected(self):
        out=scan_depth_books([self.book("a",99,100,timestamp=1000),
                              self.book("b",103,104,timestamp=1000)],
                             now_ms=10000,max_age_ms=5000)
        self.assertEqual(out,[])

    def test_crossed_rejected(self):
        self.assertIsNone(self.book("a",105,100))

if __name__=="__main__":
    unittest.main()
