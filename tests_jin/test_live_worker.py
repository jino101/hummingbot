import json
import tempfile
import time
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import MagicMock,patch

from jin_trading.live_worker import LiveWorker
from jin_trading.store import Store
from test_arbitrage import triangle


class LiveWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'live.sqlite')
        self.config=json.loads(Path('jin_trading/config.5usdt.json').read_text())
        self.config['mode']='live';self.config['bots']={
            'one':{'exchange':'kucoin','budget':'2.5'},'two':{'exchange':'kucoin','budget':'2.5'}}
        self.config['fees']={'kucoin':'.002'}
        self.store.configure({'one':'2.5','two':'2.5'})
        self.client=MagicMock();self.client.id='kucoin'
        self.client.fetch_balance.return_value={'free':{'USDT':5},'total':{'USDT':5}}
        self.client.request.return_value={'data':{'permission':'General,Spot'}}
        self.client.fetch_trading_fee.return_value={'taker':'.001'}
        self.feed=MagicMock();self.feed.exchange='kucoin'
        self.books={b.pair:b for b in triangle()}
        self.feed.book.side_effect=lambda pair:self.books[pair]

    def tearDown(self):self.tmp.cleanup()

    def worker(self):
        with patch('jin_trading.live_worker.PublicFeed',return_value=self.feed):
            return LiveWorker(self.store,self.config,{'kucoin':self.client},True)

    def test_explicit_activation_and_separate_account_scope(self):
        with self.assertRaises(ValueError):LiveWorker(self.store,self.config,{'kucoin':self.client})
        self.client.create_order.assert_not_called()
        self.client.fetch_balance.return_value={'free':{'USDT':100},'total':{'USDT':100}}
        worker=self.worker()
        self.assertTrue(worker.sync_accounts())
        self.assertTrue(worker.portfolio.snapshot()['halt'])
        worker.process_books(list(self.books.values()),[])
        self.client.create_order.assert_not_called()

    def test_real_allocations_are_atomic_and_survive_restart(self):
        worker=self.worker()
        self.client.fetch_balance.return_value={'free':{'USDT':4},'total':{'USDT':4}}
        self.assertEqual(worker.sync_accounts(),[])
        self.assertEqual([b['capital'] for b in self.store.snapshot()['bots']],['2','2'])
        self.assertFalse(self.store.snapshot()['halt'])
        self.assertEqual(self.store.snapshot()['bots'][0]['pnl'],'0')
        self.store.configure({'one':'2.5','two':'2.5'})
        self.client.fetch_balance.return_value={'free':{'USDT':3.6},'total':{'USDT':3.6}}
        worker.sync_accounts()
        self.assertTrue(worker.portfolio.snapshot()['halt'])
        with self.assertRaises(ValueError):worker.portfolio.reset()
        self.assertTrue(self.store.snapshot()['halt'])

    def test_stopped_bots_permissions_and_unknown_fees_never_submit(self):
        worker=self.worker();worker.sync_accounts()
        worker.process_books(list(self.books.values()),[])
        self.client.create_order.assert_not_called()
        self.store.control('one',True)
        self.client.fetch_trading_fee.side_effect=TimeoutError('uncertain fee')
        worker.brokers['kucoin'].verified_fees.clear()
        worker.process_books(list(self.books.values()),[])
        self.client.create_order.assert_not_called()
        self.client.request.return_value={'data':{'permission':'General,Spot,Withdraw'}}
        worker.sync_accounts();self.assertFalse(worker.portfolio.snapshot()['ready'])

    def test_enabled_bot_executes_via_shared_engine_and_verified_fees(self):
        worker=self.worker();worker.sync_accounts();self.store.control('one',True)
        worker.engine=MagicMock()
        worker.engine.triangle.return_value={'input':'1','output':'1.1'}
        worker.process_books(list(self.books.values()),[])
        self.assertEqual(worker.engine.triangle.call_count,1)
        self.assertEqual(worker.engine.triangle.call_args.args[:2],('one','kucoin'))
        self.assertEqual(worker.engine.triangle.call_args.args[3],D('1.25'))
        self.assertEqual(len(self.store.snapshot()['trades']),1)
        self.client.create_order.assert_not_called()

    def test_snapshot_failure_invalidates_and_stops_shared_engine(self):
        worker=self.worker();worker.sync_accounts();worker.engine=MagicMock()
        self.client.fetch_balance.side_effect=TimeoutError('account missing')
        worker.tick()
        self.assertFalse(worker.portfolio.snapshot()['ready'])
        worker.engine.stop_all.assert_called()
        worker.engine.triangle.assert_not_called()

    def test_live_config_rejects_inconsistent_or_unimplemented_allocations(self):
        for change in ({'max_age':10},{'fees':{'kucoin':'.001','binance':'.001'}},
                       {'bots':{'one':{'exchange':'kucoin','strategy':'grid','pair':'A-USDT','budget':'5'}}}):
            with patch.dict(self.config,change):
                with self.assertRaises(ValueError):self.worker()
