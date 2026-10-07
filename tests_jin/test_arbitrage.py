import time
import unittest
from decimal import Decimal as D

from jin_trading.arbitrage import Book, Opportunity, number, scan, scan_with_diagnostics


def book(pair, bid, ask, exchange='kucoin', timestamp=None, seq='1', minimum='0', step='0.000001', depth='1000', fee='0.001'):
    return Book(exchange, pair, ((D(bid), D(depth)),), ((D(ask), D(depth)),),
                time.time() if timestamp is None else timestamp, seq, D(fee), D(step), D('0'), D(minimum))


def triangle(now=None):
    now = time.time() if now is None else now
    return [book('A-USDT', '0.99', '1', timestamp=now),
            book('B-A', '0.99', '1', timestamp=now),
            book('B-USDT', '1.2', '1.21', timestamp=now)]


class ScannerTests(unittest.TestCase):
    def test_triangle_fee_depth_and_closed_route(self):
        results = scan(triangle(), D('2'), time.time())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].kind, 'triangular')
        self.assertGreater(results[0].net_fraction, D('0.18'))
        self.assertLess(results[0].net_fraction, D('0.20'))

    def test_no_profit_after_fees(self):
        self.assertEqual(scan(triangle(), D('2'), time.time(), min_profit=D('0.20')), [])

    def test_diagnostics_returns_near_miss_below_threshold(self):
        accepted, near, rejected = scan_with_diagnostics(
            triangle(), D('2'), time.time(), min_profit=D('0.20'))
        self.assertEqual(accepted, [])
        self.assertEqual(len(near), 1)
        self.assertEqual(near[0][0].kind, 'triangular')
        self.assertIn('unter Mindestgewinn', near[0][1])
        self.assertEqual(rejected, {})

    def test_diagnostics_counts_exchange_limit_rejections(self):
        limited = triangle()
        limited[0] = book('A-USDT', '0.99', '1', timestamp=time.time(), minimum='100')
        accepted, near, rejected = scan_with_diagnostics(limited, D('2'), time.time())
        self.assertEqual(accepted, [])
        self.assertEqual(near, [])
        self.assertGreater(rejected.get('Order outside exchange limits', 0), 0)

    def test_stale_future_and_missing_leg_fail_closed(self):
        now=time.time()
        self.assertEqual(scan(triangle(now-10), D('2'), now), [])
        self.assertEqual(scan(triangle(now+10), D('2'), now), [])
        self.assertEqual(scan(triangle()[:2], D('2'), now), [])

    def test_cross_exchange_two_fees(self):
        books=[book('A-USDT','0.99','1',exchange='kucoin'), book('A-USDT','1.1','1.11',exchange='binance')]
        result=scan(books,D('2'),time.time())[0]
        self.assertEqual(result.kind,'cross_exchange')
        self.assertLess(result.net_fraction,D('0.1'))

    def test_exchange_limits_and_rounding(self):
        b=book('A-USDT','0.9','1',step='0.1',minimum='1')
        self.assertEqual(b.convert('USDT',D('1.29'),D('0'))[1],D('1.1988'))
        for source, amount in [('USDT',D('0.99')),('A',D('0.9'))]:
            with self.assertRaises(ValueError): b.convert(source,amount)
        with self.assertRaises(ValueError): b.convert('C',D('1'))
        with self.assertRaises(ValueError): b.convert('A',D('-1'))
        b=Book('x','A-USDT',((D('1'),D('100')),),((D('2'),D('100')),),time.time(),'1',D('0'),D('1'),D('1'),D('0'),D('2'))
        with self.assertRaises(ValueError):b.convert('A',D('3'))

    def test_depth_walk(self):
        b=Book('x','A-USDT',((D('2'),D('1')),(D('1'),D('1'))),((D('3'),D('1')),(D('4'),D('1'))),time.time(),'1',D('0'),D('0.01'),D('0'),D('0'))
        self.assertEqual(b.convert('A',D('2'),D('0'))[1],D('3'))
        self.assertEqual(b.convert('USDT',D('7'),D('0'))[1],D('2'))
        for source in ('A','USDT'):
            with self.assertRaises(ValueError):b.convert(source,D('100'))

    def test_bad_books_and_settings(self):
        for value in ('NaN','Infinity','-Infinity'):
            with self.assertRaises(ValueError):number(value)
        for kwargs in ({'fee':'2'},{'fee':'-1'},{'step':'0'},{'minimum':'-1'},{'depth':'0'}):
            with self.assertRaises(ValueError):book('A-USDT','1','2',**kwargs)
        with self.assertRaises(ValueError):book('A-USDT','2','1')
        with self.assertRaises(ValueError):book('A-A','1','2')
        with self.assertRaises(ValueError):scan([],D('0'),time.time())
