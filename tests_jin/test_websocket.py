import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,MagicMock

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

    async def test_failed_discovery_publishes_error_and_closes(self):
        self.feed.pairs=lambda:(_ for _ in ()).throw(ValueError('offline'))
        await self.runner.run()
        self.assertIn('No supported',self.worker.store.snapshot()['bots'][0]['status']['errors'][0])
        self.client.close.assert_awaited_once()
