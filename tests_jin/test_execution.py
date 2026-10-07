import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from jin_trading.execution import ExecutionEngine, PaperBroker, order_size
from jin_trading.supervisor import Portfolio
from jin_trading.strategies import Signals, growth
from test_arbitrage import triangle, book


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.sqlite'
        self.portfolio=Portfolio(self.path);self.portfolio.register(['a','b'])
        self.books={b.pair:b for b in triangle()}
        self.a=PaperBroker(self.portfolio,'a',self.books,'2.5')
        self.b=PaperBroker(self.portfolio,'b',self.books,'2.5')
        self.a.sync();self.b.sync()
        self.engine=ExecutionEngine(self.portfolio,{'a':self.a,'b':self.b})

    def tearDown(self):self.tmp.cleanup()

    def route(self):return self.engine.triangle('bot','a',list(self.books),'1','unique')

    def test_three_legs_wallet_journal_and_restart(self):
        result=self.route()
        self.assertGreater(D(result['profit']),0)
        self.assertEqual(len(self.portfolio.orders()),3)
        self.assertEqual({r['state'] for r in self.portfolio.orders()},{'closed'})
        self.assertGreater(self.a.sync(),D('2.5'))
        restarted=Portfolio(self.path)
        self.assertEqual(restarted.snapshot()['runs'][0]['state'],'completed')
        self.assertEqual(PaperBroker(restarted,'a',self.books,'100').balances(),self.a.balances())
        with self.assertRaisesRegex(ValueError,'already used'):self.route()

    def test_unknown_submission_is_not_retried_and_survives_restart(self):
        original=self.a.submit
        def timeout(*args):original(*args);raise TimeoutError('response lost')
        with patch.object(self.a,'submit',side_effect=timeout) as submit:
            with self.assertRaisesRegex(ValueError,'unconfirmed'):self.route()
            self.assertEqual(submit.call_count,1)
        self.assertTrue(Portfolio(self.path).snapshot()['halt'])
        with self.assertRaises(ValueError):self.portfolio.reset()
        self.assertEqual(self.engine.reconcile()[0]['status'],'closed')
        self.assertEqual(len(self.portfolio.orders()),1)
        self.a.sync();self.b.sync()
        with self.assertRaises(ValueError):self.portfolio.settle_held('unique','blind reset')
        self.portfolio.settle_held('unique','ACCEPT_RECONCILED_INVENTORY')
        self.portfolio.reset()
        self.assertTrue(self.portfolio.snapshot()['ready'])

    def test_partial_fill_stops_next_leg_and_retains_exposure(self):
        run=self.portfolio.reserve('bot',[('a','USDT',D('1'),D('1'))])
        client=self.portfolio.prepare(run,'a','A-USDT','buy','1','1.01')
        self.portfolio.submitting(client)
        self.portfolio.observe(client,{'id':'exchange1','status':'canceled','filled':'.4','cost':'.4','fees':[{'currency':'USDT','cost':'.0004'}]})
        self.portfolio.finish(run,False,'partial')
        with self.assertRaises(ValueError):self.portfolio.reserve('second',[('a','USDT',1,1)])
        self.assertEqual(self.portfolio.orders()[0]['filled'],'0.4')
        self.portfolio.observe(client,{'id':'exchange1','status':'closed','filled':'.6','cost':'.6','fees':[{'currency':'USDT','cost':'.0006'}]})
        self.assertEqual(self.portfolio.orders()[0]['filled'],'0.6')
        self.assertFalse(self.portfolio.observe(client,{'id':'exchange1','status':'canceled','filled':'.4','cost':'.4','fees':[]}))
        with self.assertRaises(ValueError):self.portfolio.observe(client,{'id':'different','status':'closed','filled':'.6','cost':'.6','fees':[]})

    def test_stale_or_incomplete_route_aborts_without_latching(self):
        self.books['A-USDT']=book('A-USDT','.99','1',timestamp=time.time()-10)
        with self.assertRaisesRegex(ValueError,'Stale'):self.route()
        self.assertFalse(self.portfolio.snapshot()['halt'])
        self.assertEqual(self.portfolio.orders(),[])
        self.assertEqual(self.portfolio.snapshot()['runs'][0]['state'],'completed')

    def test_third_leg_minimum_is_checked_before_any_order(self):
        self.books['B-USDT']=book('B-USDT','1.2','1.21',minimum='100')
        with patch.object(self.a,'submit',wraps=self.a.submit) as submit:
            with self.assertRaises(ValueError):self.route()
            submit.assert_not_called()
        self.assertFalse(self.portfolio.snapshot()['halt'])
        self.assertEqual(self.portfolio.orders(),[])

    def test_live_cross_requires_asset_identity_and_rebalance_proof(self):
        live=Portfolio(Path(self.tmp.name)/'cross-live.sqlite','live')
        with self.assertRaisesRegex(ValueError,'asset identity'):
            ExecutionEngine(live,{}).cross('bot','buy','sell','A-USDT','1')

    def test_concurrent_reservations_share_ceiling(self):
        def reserve(account):
            try:return self.portfolio.reserve(account,[(account,'USDT',2,2)])
            except ValueError:return None
        with ThreadPoolExecutor(2) as pool:result=list(pool.map(reserve,['a','b']))
        self.assertEqual(sum(r is not None for r in result),1)
        with self.assertRaises(ValueError):self.portfolio.reserve('bot',[('a','USDT',1,1),('a','USDT',1,1)])
        for r in result:
            if r:self.assertTrue(self.portfolio.abort_unsubmitted(r))

    def test_loss_latch_commit_reset_and_held_inventory(self):
        self.portfolio.update_account('a','2',{'USDT':'2'})
        self.portfolio.update_account('b','2.4',{'USDT':'2.4'})
        self.assertTrue(self.portfolio.snapshot()['halt'])
        with self.assertRaisesRegex(ValueError,'threshold'):self.portfolio.reset()
        self.assertTrue(Portfolio(self.path).snapshot()['halt'])
        self.portfolio.update_account('a','2.5',{'USDT':'2.5'});self.portfolio.update_account('b','2.5',{'USDT':'2.5'})
        self.portfolio.reset()
        self.assertFalse(self.portfolio.snapshot()['halt'])

    def test_prepare_and_submission_cannot_bypass_stop(self):
        run=self.portfolio.reserve('bot',[('a','USDT',1,1)])
        client=self.portfolio.prepare(run,'a','A-USDT','buy',1,1)
        self.portfolio.halt()
        with self.assertRaises(ValueError):self.portfolio.submitting(client)
        with self.assertRaises(ValueError):self.portfolio.prepare(run,'a','A-USDT','buy',1,1)
        self.assertEqual(self.portfolio.orders()[0]['state'],'prepared')
        self.assertTrue(self.portfolio.abort_unsubmitted(run))
        self.portfolio.reset()

    def test_pending_no_fee_bad_response_and_no_release(self):
        run=self.portfolio.reserve('bot',[('a','USDT',1,1)])
        client=self.portfolio.prepare(run,'a','A-USDT','buy',1,1)
        self.portfolio.submitting(client)
        with self.assertRaises(ValueError):self.portfolio.submitting(client)
        for response in ({'id':'o','status':'closed','filled':1,'cost':1,'fees':[]},
                         {'id':'o','status':'unknown'}, {'status':'canceled'},
                         {'id':'o','status':'closed','filled':2,'cost':2,'fees':[]}):
            with self.assertRaises(ValueError):self.portfolio.observe(client,response)
        self.portfolio.observe(client,{'id':'o','status':'open','filled':0,'cost':0,'fees':[]})
        with self.assertRaises(ValueError):self.portfolio.finish(run,True)
        self.portfolio.finish(run,False)
        with self.assertRaises(ValueError):self.portfolio.settle_held(run,'ACCEPT_RECONCILED_INVENTORY')
        result=self.engine.stop_all()
        self.assertEqual(result[0]['status'],'unknown')

    def test_live_permissions_and_mode_isolation(self):
        with self.assertRaises(ValueError):Portfolio(self.path,'live')
        live=Portfolio(Path(self.tmp.name)/'live.sqlite','live');live.register(['kucoin'])
        live.update_account('kucoin',5,{'USDT':5})
        with self.assertRaises(ValueError):live.reserve('bot',[('kucoin','USDT',1,1)])
        live.update_account('kucoin',5,{'USDT':5},permissions={'read':True,'trade':True,'withdraw':False,'checked_at':time.time()})
        self.assertTrue(live.snapshot()['ready'])
        with self.assertRaises(ValueError):live.register(['other'])
        with self.assertRaises(ValueError):live.update_account('other',5,{'USDT':5})
        with self.assertRaises(ValueError):live.update_account('kucoin',-1,{'USDT':5})
        with patch('jin_trading.supervisor.time.time',return_value=time.time()+31):
            self.assertFalse(live.snapshot()['ready'])

    def test_paper_directional_inventory_and_stop(self):
        result=self.engine.directional('bot','a','A-USDT','buy',D('.5'))
        self.assertEqual(result['order']['status'],'closed')
        self.assertGreater(self.a.entry_prices()['A'],1)
        self.a.sync()
        self.engine.directional('bot','a','A-USDT','sell',D('.5'))
        self.assertNotIn('A',self.a.entry_prices())
        self.assertEqual(self.engine.stop_bot('none'),[])
        with self.assertRaises(ValueError):self.engine.directional('bot','a','A-USDT','buy',0)

    def test_prefunded_cross_and_missing_base(self):
        # Reserve both legs; sell-side base has to exist before starting.
        with self.assertRaises(ValueError):self.engine.cross('cross','a','b','A-USDT',D('.5'))
        self.engine.directional('seed','b','A-USDT','buy',D('.5'));self.b.sync()
        self.b.books=dict(self.books);self.b.books['A-USDT']=book('A-USDT','1.1','1.11',exchange='binance')
        result=self.engine.cross('cross','a','b','A-USDT',D('.5'))
        self.assertTrue(result['inventory_rebalance_required'])
        self.assertEqual(len(result['orders']),2)

    def test_minimum_depth_and_fresh_valuation(self):
        with self.assertRaises(ValueError):order_size(book('A-USDT','1','2',minimum='5'),'USDT',D('1'))
        with self.assertRaises(ValueError):order_size(book('A-USDT','1','2',depth='.01'),'USDT',D('1'))
        with self.portfolio.db() as db:db.execute('INSERT INTO paper_wallets VALUES (?,?,?)',('a','UNKNOWN','1'))
        with self.assertRaises(ValueError):self.a.sync()


class StrategyTests(unittest.TestCase):
    def test_growth_steps_are_amounts_not_risk_increases(self):
        self.assertEqual(growth('5')['daily_loss_limit'],'0.5')
        self.assertEqual(growth('10')['stress_budget'],'0.10')
        self.assertEqual(growth('1000')['next_stage'],None)
        with self.assertRaises(ValueError):growth('-1')

    def test_signal_warmup_limits_and_entry_based_stop(self):
        signal=Signals('mean_reversion',window=3)
        for _ in range(3):self.assertIsNone(signal.signal(book('A-USDT','1','1.01'),{'USDT':5},5))
        result=signal.signal(book('A-USDT','.9','.91'),{'USDT':5},5)
        self.assertEqual(result[0],'buy')
        result=signal.signal(book('A-USDT','.9','.91'),{'A':1},5,{'A':1})
        self.assertEqual(result,('sell',D('1')))
        for kind in ('momentum','grid'):
            s=Signals(kind,3)
            for _ in range(3):s.signal(book('A-USDT','1','1.01'),{'USDT':5},5)
            s.signal(book('A-USDT','1.1','1.11'),{'USDT':5},5)
        for args in [('unknown',3),('grid',1)]:
            with self.assertRaises(ValueError):Signals(*args)
