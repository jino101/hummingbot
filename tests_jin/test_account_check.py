import tempfile
import time
import unittest
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from jin_trading.account_check import check
from test_arbitrage import book, triangle


class ReadOnlyClient:
    id = 'kucoin'

    def __init__(self):
        self.fee = {'taker': '.001', 'percentage': True}
        self.fee_calls = []
        self.balance = {'free': {'USDT': '5'}, 'total': {'USDT': '5'}}
        self.order_calls = 0

    def fetch_balance(self, options):
        return self.balance

    def request(self, *args):
        return {'data': {'permission': 'General'}}

    def fetch_trading_fee(self, symbol):
        self.fee_calls.append(symbol)
        if isinstance(self.fee, Exception):
            raise self.fee
        return dict(self.fee)

    def amount_to_precision(self, symbol, amount):
        return str(amount)

    def price_to_precision(self, symbol, price):
        return str(price)

    def create_order(self, *args, **kwargs):
        self.order_calls += 1
        raise AssertionError('Read-only checks must not submit orders')


class PublicBooks:
    exchange = 'kucoin'
    fee = D('.001')

    def __init__(self, books=None):
        self.books = {b.pair: b for b in (triangle() if books is None else books)}
        self.catalogue = list(self.books)

    def pairs(self):
        return self.catalogue

    def book(self, pair):
        return self.books[pair]


class AccountCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client, self.feed = ReadOnlyClient(), PublicBooks()
        self.db = str(Path(self.tmp.name) / 'check.sqlite')

    def tearDown(self):
        self.assertEqual(self.client.order_calls, 0)
        self.tmp.cleanup()

    def report(self, amount='5'):
        return check(self.client, self.feed, amount, self.db)

    def test_personal_fees_override_public_estimates_without_mutating_feed(self):
        self.feed = PublicBooks([replace(b, fee=D('.2')) for b in triangle()])
        result = self.report()
        self.assertEqual(len(result['feasible']), 1)
        self.assertEqual(len(result['tradable_routes']), 2)
        self.assertTrue(result['personal_fees_verified'])
        self.assertFalse(result['live_ready'])
        self.assertEqual(result['trade_budget'], '2.5')
        self.assertEqual(set(self.client.fee_calls), {'A/USDT', 'B/A', 'B/USDT'})
        self.assertTrue(all(b.fee == D('.2') for b in self.feed.books.values()))
        self.assertTrue(all(D(leg['taker_fee']) == D('.001') for leg in result['feasible'][0]['legs']))

    def test_higher_personal_fees_remove_profit_but_keep_technical_routes(self):
        self.client.fee = {'taker': '.1'}
        result = self.report()
        self.assertEqual(result['feasible'], [])
        self.assertEqual(len(result['tradable_routes']), 2)
        self.assertTrue(all(r['reason'] == 'below_profit_threshold' for r in result['tradable_routes']))
        self.assertTrue(result['personal_fees_verified'])

    def test_unavailable_invalid_and_flat_fees_are_explicit_assumptions(self):
        for fee in (RuntimeError('contains-secret'), {}, {'taker': 'NaN'},
                    {'taker': '-.01'}, {'taker': '1'}, {'taker': '.001', 'percentage': False}):
            with self.subTest(fee=type(fee).__name__):
                self.client.fee = fee
                result = self.report()
                self.assertFalse(result['personal_fees_verified'])
                self.assertTrue(all(f['source'] == 'public_assumption' for f in result['fees'].values()))
                self.assertNotIn('contains-secret', str(result))

    def test_zero_personal_fee_is_verified(self):
        self.client.fee = {'taker': '0', 'percentage': True}
        self.assertTrue(self.report()['personal_fees_verified'])

    def test_emulated_fee_is_not_presented_as_account_verified(self):
        self.client.has = {'fetchTradingFee': 'emulated'}
        result = self.report()
        self.assertFalse(result['personal_fees_verified'])
        self.assertEqual(self.client.fee_calls, [])

    def test_slow_batch_expires_personal_fees_without_replacing_per_book_assumption(self):
        clock = [1000.0]
        self.feed = PublicBooks([replace(b, fee=D('.02'), timestamp=clock[0]) for b in triangle()])
        fetch = self.feed.book

        def delayed_book(pair):
            clock[0] += 50
            return replace(fetch(pair), timestamp=clock[0])

        self.feed.book = delayed_book
        with patch('jin_trading.account_check.time.time', side_effect=lambda: clock[0]):
            result = self.report()
        self.assertFalse(result['personal_fees_verified'])
        self.assertTrue(all(fee['error'] == 'StaleAccountFee' for fee in result['fees'].values()))
        self.assertTrue(all(D(fee['taker']) == D('.02') for fee in result['fees'].values()))

    def test_minimum_quantity_notional_maximum_and_precision_report_blocked_leg(self):
        for fields, reason in (({'min_notional': D('5')}, 'below_min_notional'),
                               ({'min_size': D('10')}, 'below_min_size'),
                               ({'max_size': D('.1')}, 'above_max_size'),
                               ({'step': D('10')}, 'quantity_below_step')):
            with self.subTest(reason=reason):
                self.feed = PublicBooks([replace(b, **fields) if b.pair == 'B-A' else b for b in triangle()])
                result = self.report()
                self.assertEqual(result['tradable_routes'], [])
                self.assertEqual(result['rejected_counts'], {reason: 2})
                for route in result['rejected_routes']:
                    self.assertEqual(route['rejected_leg'], 2)
                    self.assertEqual(route['legs'][1]['pair'], 'B-A')
                    self.assertIn('min_notional', route['legs'][1])
                    self.assertEqual(route['legs'][2]['status'], 'not_checked')

    def test_insufficient_depth_is_separate_from_market_minimum(self):
        self.feed.books['B-A'] = book('B-A', '.99', '1', depth='.1')
        result = self.report()
        self.assertEqual(result['rejected_counts'], {'insufficient_depth': 2})

    def test_client_precision_that_changes_quantity_is_rejected(self):
        self.client.amount_to_precision = lambda *args: '.01'
        result = self.report()
        self.assertEqual(result['rejected_counts'], {'quantity_precision_changed': 2})

    def test_price_narrowing_must_still_cover_required_depth(self):
        self.client.price_to_precision = lambda symbol, price: str(D(str(price)) / D('2'))
        result = self.report()
        self.assertEqual(result['rejected_counts'], {'insufficient_depth_after_precision': 2})

    def test_missing_precision_and_widened_buy_price_are_rejected(self):
        with patch.object(self.client, 'price_to_precision', side_effect=RuntimeError('private-data')):
            result = self.report()
        self.assertEqual(result['rejected_counts'], {'precision_unavailable': 2})
        self.assertNotIn('private-data', str(result))
        self.client.price_to_precision = lambda symbol, price: str(D(str(price)) * D('2'))
        self.assertEqual(self.report()['rejected_counts'], {'price_precision_widens_limit': 2})

    def test_stale_and_missing_books_have_route_diagnostics(self):
        for offset in (-10, 10):
            self.feed = PublicBooks(triangle(time.time() + offset))
            self.assertEqual(self.report()['rejected_counts'], {'stale_order_book': 2})
        self.feed = PublicBooks()
        del self.feed.books['B-A']
        result = self.report()
        self.assertEqual(result['rejected_counts'], {'book_unavailable': 2})
        self.assertIn('B-A: KeyError', result['errors'])

    def test_no_free_capital_and_invalid_requested_capital(self):
        self.client.balance = {'free': {'USDT': '0'}, 'total': {'USDT': '5'}}
        result = self.report()
        self.assertEqual(result['trade_budget'], '0.0')
        self.assertEqual(result['feasible'], [])
        self.assertEqual(self.client.fee_calls, [])
        for value in ('0', '-1', 'NaN'):
            with self.assertRaises(ValueError):
                self.report(value)

    def test_available_capital_is_capped_and_duplicate_batch_routes_are_not_duplicated(self):
        self.client.balance = {'free': {'USDT': '3'}, 'total': {'USDT': '3'}}
        pair_batch = tuple(self.feed.pairs())
        with patch('jin_trading.account_check.plan_batches', return_value=[pair_batch, pair_batch]):
            result = self.report()
        self.assertEqual(result['trade_budget'], '1.5')
        self.assertEqual(result['checked_routes'], 2)
        self.assertEqual(len(self.client.fee_calls), 3)

    def test_single_market_does_not_invent_a_triangle(self):
        self.feed = PublicBooks(triangle()[:1])
        result = self.report()
        self.assertEqual(result['checked_routes'], 0)
        self.assertEqual(result['tradable_routes'], [])


if __name__ == '__main__':
    unittest.main()
