import time
import threading
import unittest
from decimal import Decimal as D
from unittest.mock import patch
from urllib.error import HTTPError

from jin_trading.universe import plan_batches, route_groups, plan_venue_batches
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

    def test_venue_plans_keep_small_catalogue_independent_and_complete(self):
        small = ('A-USDT', 'B-A', 'B-USDT')
        large = {'BTC-USDT'} | {p for i in range(100) for p in (f'C{i}-USDT', f'C{i}-BTC')}
        plans = plan_venue_batches({'kucoin': small, 'binance': large}, 3)
        self.assertEqual(plans['kucoin']['batch_count'], 1)
        self.assertEqual(set(plans['kucoin']['batches'][0]), set(small))
        self.assertTrue(all(set(batch) <= large for batch in plans['binance']['batches']))
        self.assertEqual({p for b in plans['binance']['batches'] for p in b}, large)
        for group in route_groups(large):
            self.assertTrue(any(set(group) <= set(batch) for batch in plans['binance']['batches']))

    def test_required_valuation_and_routes_share_at_most_twenty_slots(self):
        required = tuple(f'V{i}-USDT' for i in range(17))
        triangle_pairs = ('A-USDT', 'B-A', 'B-USDT')
        plan = plan_venue_batches({'kucoin': (*required, *triangle_pairs)}, 12,
                                 required={'kucoin': required})['kucoin']
        self.assertFalse(plan['capacity_exhausted'])
        self.assertTrue(all(len(batch) <= 20 and set(required) <= set(batch) for batch in plan['batches']))
        self.assertTrue(any(set(triangle_pairs) <= set(batch) for batch in plan['batches']))
        crowded = tuple(f'V{i}-USDT' for i in range(21))
        plan = plan_venue_batches({'kucoin': (*crowded, *triangle_pairs)}, required={'kucoin': crowded})['kucoin']
        self.assertTrue(plan['capacity_exhausted'])
        self.assertEqual(len(plan['batches'][0]), 20)
        self.assertFalse(any(set(triangle_pairs) <= set(batch) for batch in plan['batches']))

    def test_missing_required_and_denied_markets_are_reported_without_fake_triangle(self):
        plan = plan_venue_batches({'kucoin': ['A-USDT', 'B-A', 'B-USDT']}, denied=['A-USDT'],
                                 required={'kucoin': ['A-USDT', 'MISSING-USDT']})['kucoin']
        self.assertEqual(plan['missing_required_pairs'], ('MISSING-USDT',))
        self.assertTrue(all('A-USDT' in batch for batch in plan['batches']))
        self.assertTrue(all('B-A' not in batch for batch in plan['batches']))
        for size in (True, 2, 21):
            with self.assertRaises(ValueError):plan_venue_batches({}, size)


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
        self.assertEqual(self.worker.universe_status['scheduled_pairs'], 21)
        self.assertTrue(all(v['scheduled_pairs'] == 7 for v in self.worker.universe_status['venues'].values()))
        for feed in self.worker.feeds.values():
            feed.pairs = lambda: (_ for _ in ()).throw(ValueError('offline'))
        self.worker.tick()
        state = self.store.snapshot()
        self.assertEqual(len(state['trades']), 0)
        self.assertEqual(len(state['bots'][0]['status']['errors']), 3)

    def test_kucoin_receives_a_complete_batch_every_cycle_among_larger_foreign_catalogues(self):
        self.config['pair_mode']='auto';self.config['batch_size']=3
        small=('A-USDT','B-A','B-USDT')
        foreign=tuple(f'C{i}-USDT' for i in range(30))
        received=[]
        for name,feed in self.worker.feeds.items():
            pairs=small if name=='kucoin' else foreign
            feed.pairs=lambda pairs=pairs:pairs
            feed.book=lambda pair,name=name:received.append((name,pair))
        with patch.object(self.worker,'process_books'):
            for _ in range(4):
                received.clear();self.worker.tick()
                self.assertEqual({p for ex,p in received if ex=='kucoin'},set(small))
                self.assertEqual(self.worker.universe_status['venues']['kucoin']['batch_number'],1)
                self.assertTrue(all(p in foreign for ex,p in received if ex!='kucoin'))

    def test_slow_foreign_discovery_does_not_block_refresh_or_duplicate_inflight_work(self):
        self.config['pair_mode']='auto';self.config['max_age']=.05
        waiting=threading.Event();release=threading.Event();calls=[]
        def slow():
            calls.append('discovery');waiting.set();release.wait(3);return ()
        self.worker.feeds['binance'].pairs=slow
        for name,feed in self.worker.feeds.items():
            if name=='binance':continue
            feed.pairs=lambda:('A-USDT','B-A','B-USDT')
            feed.book=lambda pair,name=name:calls.append((name,pair))
        try:
            with patch.object(self.worker,'process_books'):
                self.worker.tick();self.assertTrue(waiting.is_set())
                self.assertEqual(sum(isinstance(x,tuple) and x[0]=='kucoin' for x in calls),3)
                self.worker.tick()
                self.assertEqual(sum(isinstance(x,tuple) and x[0]=='kucoin' for x in calls),6)
                self.assertEqual(calls.count('discovery'),1)
        finally:
            release.set()
            for future in self.worker._feed_futures.values():future.result(timeout=3)

    def test_five_usdt_profile_only_configures_kucoin(self):
        config=test_feeds_worker.load_config('jin_trading/config.5usdt.json')
        self.assertEqual(set(config['fees']),{'kucoin'})
        self.assertEqual({spec['exchange'] for spec in config['bots'].values()},{'kucoin'})

    def test_bot_specific_signal_requirements_keep_shared_inventory_valuations(self):
        for name,spec in self.config['bots'].items():
            spec.update(exchange='kucoin',strategy='momentum',
                        pair='A-USDT' if name=='kucoin-triangle' else 'MISSING-USDT')
        worker=test_feeds_worker.Worker(self.store,self.config)
        self.assertEqual(worker.required_pairs('kucoin'),('A-USDT','MISSING-USDT'))
        self.assertEqual(worker.required_pairs('kucoin',signal_bot='kucoin-triangle'),('A-USDT',))
        with worker.portfolio.db() as db:
            db.execute('INSERT INTO paper_wallets VALUES (?,?,?)',('binance-triangle','C','1'))
        self.assertEqual(worker.required_pairs('kucoin',signal_bot='kucoin-triangle'),('A-USDT','C-USDT'))

