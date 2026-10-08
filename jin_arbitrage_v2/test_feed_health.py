import unittest
from .feed_health import FeedHealth, fresh_quote
from .models import Quote, VenueType

class TestFeedHealth(unittest.TestCase):
    def test_health_stale_without_quote(self):
        self.assertTrue(FeedHealth("demo").is_stale(now_ms=10000, max_age_ms=5000))

    def test_health_fresh_then_stale(self):
        h = FeedHealth("demo", last_quote_ms=9000)
        self.assertFalse(h.is_stale(now_ms=10000, max_age_ms=5000))
        self.assertTrue(h.is_stale(now_ms=15001, max_age_ms=5000))

    def test_fresh_quote_rejects_old_and_future(self):
        q = Quote("x", VenueType.CEX, "SOL/USDT", 99, 100, timestamp_ms=9000)
        self.assertTrue(fresh_quote(q, now_ms=10000, max_age_ms=5000))
        self.assertFalse(fresh_quote(q, now_ms=14001, max_age_ms=5000))
        q.timestamp_ms = 11000
        self.assertFalse(fresh_quote(q, now_ms=10000, max_age_ms=5000))

if __name__ == "__main__":
    unittest.main()
