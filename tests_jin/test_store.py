import tempfile
import threading
import time
import unittest
from decimal import Decimal as D
from pathlib import Path

from jin_trading.arbitrage import Opportunity
from jin_trading.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'state.sqlite')
        self.store.configure({'one':'2.5','two':'2.5'})
        self.store.snapshot()

    def tearDown(self):self.tmp.cleanup()

    def chance(self, seq='1', amount='1', output='1.02', kind='triangular'):
        return Opportunity(kind,(('kucoin','A-USDT'),),D(amount),D(output),seq)

    def test_start_stop_reinvestment_and_restart(self):
        self.assertFalse(self.store.paper_fill('one',self.chance()))
        self.store.control('one',True)
        self.assertTrue(self.store.paper_fill('one',self.chance()))
        self.assertFalse(self.store.paper_fill('one',self.chance()))
        self.store.configure({'one':'2.5','two':'2.5'})
        state=self.store.snapshot()
        self.assertEqual(state['capital'],'5.02')
        self.assertEqual(state['bots'][0]['max_order'],'1.260')
        self.store.control('one',False)
        self.assertFalse(self.store.paper_fill('one',self.chance('2')))

    def test_latch_persisted_and_explicit_reset(self):
        self.store.control('one',True)
        self.store.emergency()
        with self.assertRaises(ValueError):self.store.control('two',True)
        self.assertFalse(self.store.paper_fill('one',self.chance()))
        reloaded=Store(self.store.path)
        self.assertTrue(reloaded.snapshot()['halt'])
        reloaded.reset()
        self.assertFalse(reloaded.snapshot()['halt'])
        self.assertFalse(any(b['enabled'] for b in reloaded.snapshot()['bots']))

    def test_global_loss_includes_both_bots_and_no_reset_bypass(self):
        with self.store.connect() as db:
            db.execute("UPDATE bots SET capital='2.25'")
        self.assertTrue(self.store.snapshot()['halt'])
        with self.assertRaises(ValueError):self.store.reset()
        with self.assertRaises(ValueError):self.store.control('one',True)

    def test_midnight_changes_baseline_but_preserves_latch(self):
        self.store.emergency()
        with self.store.connect() as db:db.execute("UPDATE settings SET value='2000-01-01' WHERE key='day'")
        self.assertTrue(self.store.snapshot()['halt'])

    def test_rejected_start_and_reset_commit_loss_latch(self):
        for action in (lambda: self.store.control('two', True), self.store.reset):
            with self.store.connect() as db:
                db.execute("UPDATE bots SET capital='2.2', enabled=1")
                db.execute("UPDATE settings SET value='0' WHERE key='halt'")
            with self.assertRaises(ValueError):action()
            with self.store.connect() as db:
                self.assertEqual(self.store._get(db, 'halt'), '1')
                self.assertFalse(any(r[0] for r in db.execute('SELECT enabled FROM bots')))

    def test_invalid_budget_changes_rollback(self):
        for budget in ({'one':'3','two':'2'},{'one':'-1','two':'6'},{'one':'5'}):
            with self.assertRaises(ValueError):self.store.configure(budget)
        self.assertEqual(len(self.store.snapshot()['bots']),2)
        with self.assertRaises(ValueError):self.store.control('absent',True)
        with self.assertRaises(ValueError):self.store.configure({'one':'4'})

    def test_budget_stress_and_cross_exchange_no_fill(self):
        self.store.control('one',True)
        for chance in (self.chance(amount='2'), self.chance(output='0.5'),
                       self.chance(kind='cross_exchange'), self.chance(amount='0')):
            self.assertFalse(self.store.paper_fill('one',chance))
        self.store.publish('one',{'feed':'test'})
        self.assertEqual(self.store.snapshot()['bots'][0]['status']['feed'],'test')

    def test_explicit_paper_budget_reset(self):
        self.store.control('one',True)
        self.assertTrue(self.store.paper_fill('one',self.chance()))
        self.store.emergency()
        self.store.reset_budgets({'one':'50','two':'50'})
        state=self.store.snapshot()
        self.assertEqual(state['capital'],'100')
        self.assertFalse(state['halt'])
        self.assertEqual(len(state['trades']),0)
        self.assertTrue(all(not bot['enabled'] for bot in state['bots']))
        self.assertEqual({bot['initial'] for bot in state['bots']},{'50'})

    def test_concurrent_duplicate_fills_are_atomic(self):
        self.store.control('one',True)
        results=[]
        threads=[threading.Thread(target=lambda:results.append(self.store.paper_fill('one',self.chance()))) for _ in range(8)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(sum(results),1)
        self.assertEqual(len(self.store.snapshot()['trades']),1)
