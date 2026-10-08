import unittest
from .config import V2Config
from .models import Quote, VenueType
from .opportunity import cross_venue_opportunities
from .triangular import scan_triangles

class TestV2(unittest.TestCase):
    def test_cross(self):
        qs = [
            Quote("a", VenueType.CEX, "SOL/USDT", bid=99, ask=100, fee_pct=.1),
            Quote("b", VenueType.CEX, "SOL/USDT", bid=102, ask=103, fee_pct=.1),
        ]
        ops = cross_venue_opportunities(qs, 25)
        self.assertTrue(ops and ops[0].net_pct > 0)

    def test_triangle(self):
        rates = {("USDT","SOL"):0.01,("SOL","BTC"):0.002,("BTC","USDT"):51000}
        ops = scan_triangles("demo", rates, ["USDT"], fee_pct=.05)
        self.assertTrue(ops)

if __name__ == "__main__":
    unittest.main()
