import time
import unittest
from decimal import Decimal as D
from unittest.mock import patch
from urllib.error import HTTPError

from jin_trading.universe import plan_batches, route_groups
from jin_trading.feeds import PublicFeed
from jin_trading.arbitrage import Book, scan
from test_arbitrage import triangle
import test_feeds_worker


class UniverseTests(unittest.TestCase):
    def test_discovery_cache_and_spot_eligibility(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return {'symbols': [{'status': 'TRADING', 'isSpotTradingAllowed': False,
                                'orderTypes': ['MARKET'], 'baseAsset': 'A', 'quoteAsset': 'USDT', 'filters': []}]}
        feed = PublicFeed('binance', '0.002', fetch)
        self.assertEqual(feed.pairs(), ())
        self.assertEqual(feed.pairs(), ())
        self.assertEqual(len(calls), 1)

    def test_all_2000_coins_scheduled_with_complete_triangles(self):
        pairs = {'BTC-USDT'} | {p for i in range(2000) for p in (f'C{i}-USDT', f'C{i}-BTC')}
        groups = route_groups(pairs)
        batches = plan_batches({'kucoin': pairs}, 12)
        self.assertEqual(set(pairs), {p for batch in batches for p in batch})
        self.assertTrue(all(len(batch) <= 12 for batch in batches))
        for group in groups:
            self.assertTrue(any(set(group) <= set(batch) for batch in batches))

    def test_no_triangle_using_different_venues_or_denied_pair(self):
        self.assertEqual(plan_batches({'a': ['A-USDT', 'A-BTC'], 'b': ['BTC-USDT']}), [('A-USDT', 'BTC-USDT')])
        batches = plan_batches({'a': ['A-USDT', 'A-BTC', 'BTC-USDT']}, denied=['A-USDT'])
        self.assertEqual(batches, [('BTC-USDT',)])

    def test_scanner_large_disconnected_universe_and_original_profit(self):
        books = triangle()
        now = time.time()
        expected = scan(books, D('1'), now)
        books += [Book('kucoin', f'C{i}-USDT', ((D('1'), D('100')),), ((D('2'), D('100')),),
                       now, str(i), D('0'), D('0.001'), D('0'), D('0')) for i in range(2000)]
        self.assertEqual(scan(books, D('1'), now), expected)

    def test_rate_limit_cooldown_prevents_more_requests(self):
        calls = []
        def fetch(url):
            calls.append(url)
            raise HTTPError(url, 429, 'rate limited', {'Retry-After': '120'}, None)
        feed = PublicFeed('kucoin', '0.002', fetch)
        with self.assertRaises(HTTPError): feed.pairs()
        with self.assertRaises(ValueError): feed.pairs()
        self.assertEqual(len(calls), 1)


class AutoWorkerTests(unittest.TestCase):
    setUp = test_feeds_worker.WorkerTests.setUp
    tearDown = test_feeds_worker.WorkerTests.tearDown
    def test_rotation_and_discovery_failure_closed(self):
        self.worker.config['pair_mode'] = 'auto'
        self.worker.config['batch_size'] = 3
        received = []
        pairs = [f'C{i}-USDT' for i in range(7)]
        for feed in self.worker.feeds.values():
            feed.pairs = lambda: pairs
            feed.book = lambda pair: received.append(pair)
        with patch.object(self.worker, 'process_books'):
            for _ in range(3): self.worker.tick()
        self.assertEqual(set(received), set(pairs))
        self.assertEqual(self.worker.universe_status['scheduled_pairs'], 7)
        for feed in self.worker.feeds.values():
            feed.pairs = lambda: (_ for _ in ()).throw(ValueError('offline'))
        self.worker.tick()
        state = self.store.snapshot()
        self.assertEqual(len(state['trades']), 0)
        self.assertEqual(len(state['bots'][0]['status']['errors']), 3)
