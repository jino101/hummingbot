import unittest
from .triangular_depth import ConversionBook, convert, scan_triangle_depth

class TriangularDepthTests(unittest.TestCase):
    def test_convert_rejects_insufficient_depth(self):
        book = ConversionBook("USD", "A", ((50, 2.0),), 0.0)
        self.assertEqual(convert(100, book), 0.0)

    def test_profitable_triangle(self):
        books = {
            ("USD", "A"): ConversionBook("USD", "A", ((1000, 2.0),), 0.0),
            ("A", "B"): ConversionBook("A", "B", ((2000, 1.0),), 0.0),
            ("B", "USD"): ConversionBook("B", "USD", ((2000, 0.51),), 0.0),
        }
        found = scan_triangle_depth("paper", "USD", 100, books, 1.0)
        self.assertEqual(len(found), 1)
        self.assertGreater(found[0]["net_pct"], 1.0)

if __name__ == "__main__":
    unittest.main()
