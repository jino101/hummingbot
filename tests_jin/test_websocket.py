import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,MagicMock,patch

from jin_trading.store import Store
from jin_trading.worker import Worker,load_config
from jin_trading.websocket import WebSocketRunner,snapshot
from test_arbitrage import triangle


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();store=Store(Path(self.tmp.name)/'paper.sqlite')
        config=load_config('jin_trading/config.example.json');config['fees']={'kucoin':'.001'}
        config['bots']={'bot':{'exchange':'kucoin','budget':'5'}};store.configure({'bot':'5'})
        self.worker=Worker(store,config);self.client=MagicMock();self.client.has={'unWatchOrderBook':True}
        self.client.close=AsyncMock();self.client.load_markets=AsyncMock();self.client.un_watch_order_book=AsyncMock()
        self.runner=WebSocketRunner(self.worker,{'kucoin':self.client},5)
        self.feed=self.worker.feeds['kucoin'];self.feed.rules={b.pair:(b.step,b.min_size,b.min_notional,b.max_size) for b in triangle()}
        self.feed.pairs=lambda:tuple(self.feed.rules)

    async def asyncTearDown(self):self.tmp.cleanup()

    def test_rule_timestamp_nonce_and_snapshot_validation(self):
        raw={'bids':[['1','100']],'asks':[['1.1','100']],'timestamp':1000000,'nonce':12}
        quote=snapshot('kucoin','A-USDT',raw,self.feed.rules['A-USDT'],'.001',1001)
        self.assertEqual(quote.timestamp,1000);self.assertEqual(quote.sequence,'12')
        del raw['timestamp'];del raw['nonce']
        quote=snapshot('kucoin','A-USDT',raw,self.feed.rules['A-USDT'],'.001',1001)
        self.assertEqual(quote.timestamp,1001);self.assertTrue(quote.sequence)
        with self.assertRaises(ValueError):WebSocketRunner(self.worker,{},5)

    async def test_producer_does_not_refresh_cached_nonce_and_unsubscribes(self):
        raw={'bids':[['1','100']],'asks':[['1.1','100']],'nonce':12}
        async def watch(*args):
            if self.client.watch_order_book.call_count>2:self.worker.stop.set()
            return raw
        self.client.watch_order_book=AsyncMock(side_effect=watch)
        await self.runner.watch('kucoin','A-USDT')
        self.assertEqual(self.runner.queue.qsize(),1)
        self.client.un_watch_order_book.assert_awaited_once()
        self.worker.stop.clear();self.client.watch_order_book.reset_mock()
        await self.runner.watch('kucoin','A-USDT')
        self.assertEqual(self.runner.queue.qsize(),1,'Resubscription cannot renew an unchanged book')

    async def test_consumer_executes_complete_triangle_and_closes_clients(self):
        self.worker.store.control('bot',True)
        quotes={b.pair:b for b in triangle()}
        async def watch(symbol,*args):
            b=quotes[symbol.replace('/','-')]
            await asyncio.sleep(.01)
            return {'bids':[[str(p),str(q)] for p,q in b.bids],'asks':[[str(p),str(q)] for p,q in b.asks],
                    'timestamp':int(time.time()*1000),'nonce':1}
        self.client.watch_order_book=AsyncMock(side_effect=watch)
        task=asyncio.create_task(self.runner.run())
        for _ in range(100):
            await asyncio.sleep(.01)
            if self.worker.store.snapshot()['trades']:break
        self.worker.stop.set();await asyncio.wait_for(task,2)
        self.assertEqual(len(self.worker.store.snapshot()['trades']),1)
        self.client.close.assert_awaited_once()
        self.assertIn('median_event_age_ms',self.worker.universe_status['websocket'])

    async def test_failed_discovery_retries_with_backoff_until_stopped(self):
        self.feed.pairs=lambda:(_ for _ in ()).throw(ValueError('offline'))
        delays=[]
        async def pause(seconds,consumer):
            delays.append(seconds)
            if len(delays)==7:self.worker.stop.set()
        self.runner.pause=pause
        await self.runner.run()
        self.assertIn('No supported',self.worker.store.snapshot()['bots'][0]['status']['errors'][0])
        self.assertEqual(delays,[1,2,4,8,16,30,30])
        self.assertEqual(self.worker.universe_status['active_subscriptions'],{})
        self.client.close.assert_awaited_once()

    async def test_discovery_recovers_without_restarting_server(self):
        calls=0
        def pairs():
            nonlocal calls
            calls+=1
            if calls==1:raise ValueError('temporary outage')
            return tuple(self.feed.rules)
        self.feed.pairs=pairs
        async def pause(seconds,consumer):
            if calls>1:
                self.assertTrue(self.worker.universe_status['active_subscriptions']['kucoin'])
                self.worker.stop.set()
        self.runner.pause=pause
        await self.runner.run()
        self.assertEqual(calls,2)
        self.assertNotIn('discovery_retry_seconds',self.worker.universe_status)
        self.assertNotIn('kucoin:discovery',self.runner.errors)
        self.client.close.assert_awaited_once()

    async def test_discovery_failure_after_rotation_recovers(self):
        calls=0
        def pairs():
            nonlocal calls
            calls+=1
            if calls==2:raise ValueError('catalogue outage')
            return tuple(self.feed.rules)
        self.feed.pairs=pairs
        clock=[1000.0]
        delays=[]
        async def pause(seconds,consumer):
            delays.append(seconds)
            if calls==1:clock[0]+=901
            elif calls==3:self.worker.stop.set()
        self.runner.pause=pause
        self.runner.clock=lambda:clock[0]
        await self.runner.run()
        self.assertEqual(calls,3)
        self.assertEqual(delays,[5,1,5])

    async def test_retry_wait_is_interruptible(self):
        consumer=asyncio.create_task(asyncio.sleep(100))
        task=asyncio.create_task(self.runner.pause(30,consumer))
        await asyncio.sleep(.01)
        self.worker.stop.set()
        await asyncio.wait_for(task,.5)
        consumer.cancel()
        await asyncio.gather(consumer,return_exceptions=True)

    async def test_catalogue_refresh_includes_new_market_and_reloads_client_rules(self):
        before=await self.runner.discover()
        self.feed.rules['C-USDT']=self.feed.rules['A-USDT']
        after=await self.runner.discover()
        self.assertNotIn('C-USDT',before['kucoin'])
        self.assertIn('C-USDT',after['kucoin'])
        self.assertEqual(self.client.load_markets.await_count,2)

    async def test_slow_foreign_market_loading_does_not_delay_kucoin_subscriptions(self):
        foreign=MagicMock();foreign.close=AsyncMock()
        entered=asyncio.Event();release=asyncio.Event();watching=asyncio.Event()
        async def load(**kwargs):
            entered.set();await release.wait()
        foreign.load_markets=AsyncMock(side_effect=load)
        feed=MagicMock();feed.pairs.return_value=('X-USDT','Y-X','Y-USDT')
        self.worker.feeds['binance']=feed
        runner=WebSocketRunner(self.worker,{'kucoin':self.client,'binance':foreign},5)
        watched=[]
        async def watch(name,pair):
            watched.append((name,pair))
            if name=='kucoin':watching.set()
            await asyncio.sleep(10)
        runner.watch=watch
        task=asyncio.create_task(runner.run())
        try:
            await asyncio.wait_for(entered.wait(),1)
            await asyncio.wait_for(watching.wait(),1)
            kucoin=self.worker.universe_status['venues']['kucoin']
            self.assertEqual(set(kucoin['active_subscriptions']),set(self.feed.rules))
            self.assertEqual(kucoin['active_subscriptions'],kucoin['selected_pairs'])
            self.assertFalse(any(name=='binance' for name,pair in watched))
        finally:
            self.worker.stop.set();release.set();await asyncio.wait_for(task,2)
        foreign.close.assert_awaited_once()

    async def test_required_subscriptions_and_complete_triangle_never_exceed_twenty(self):
        required=tuple(f'V{i}-USDT' for i in range(17))
        original=tuple(self.feed.rules)
        self.feed.pairs=lambda:(*original,*required)
        watched=[]
        async def watch(name,pair):
            watched.append(pair);await asyncio.sleep(10)
        async def pause(seconds,consumer):
            await asyncio.sleep(.01);self.worker.stop.set()
        self.runner.watch=watch;self.runner.pause=pause
        with patch.object(self.worker,'required_pairs',return_value=required):
            await self.runner.run()
        self.assertEqual(len(watched),20)
        self.assertTrue(set(required)<=set(watched))
        self.assertTrue(set(original)<=set(watched))
        row=self.worker.universe_status['venues']['kucoin']
        self.assertFalse(row['capacity_exhausted'])
        self.assertEqual(set(row['active_subscriptions']),set(watched))

    async def test_exhausted_capacity_is_visible_and_does_not_split_a_triangle(self):
        required=tuple(f'V{i}-USDT' for i in range(21))
        original=tuple(self.feed.rules)
        self.feed.pairs=lambda:(*original,*required)
        watched=[]
        async def watch(name,pair):
            watched.append(pair);await asyncio.sleep(10)
        async def pause(seconds,consumer):
            await asyncio.sleep(.01);self.worker.stop.set()
        self.runner.watch=watch;self.runner.pause=pause
        with patch.object(self.worker,'required_pairs',return_value=required):
            await self.runner.run()
        self.assertEqual(len(watched),20)
        self.assertFalse(set(original)&set(watched))
        self.assertTrue(self.worker.universe_status['venues']['kucoin']['capacity_exhausted'])
        self.assertIn('kucoin:capacity',self.runner.errors)

