import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jin_trading.runtime import WorkerRuntime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.fail_processing = False
        self.account = {'ready': True, 'halt': False}
        self.ledger = {'halt': False}

        def process(books, errors):
            if self.fail_processing:
                raise ValueError('a credential must never appear in runtime status')

        self.worker = SimpleNamespace(
            config={'max_age': 3, 'bots': {'bot': {'exchange': 'kucoin'}}},
            stop=threading.Event(), process_books=process, required_pairs=lambda exchange, signal_bot=None: (),
            portfolio=SimpleNamespace(snapshot=lambda: dict(self.account)),
            store=SimpleNamespace(snapshot=lambda: dict(self.ledger)))
        self.runtime = WorkerRuntime(self.worker, clock=lambda: self.now)
        self.entered = threading.Event()

    def tearDown(self):
        self.worker.stop.set()
        if self.runtime.thread and self.runtime.thread.ident:
            self.runtime.thread.join(timeout=2)
            self.assertFalse(self.runtime.thread.is_alive())

    def start(self):
        def target():
            self.entered.set()
            self.worker.stop.wait()
        self.runtime.start(target)
        self.assertTrue(self.entered.wait(2))

    def book(self, exchange='kucoin', stamp=None, pair='A-USDT', sequence=None):
        stamp = self.now if stamp is None else stamp
        return SimpleNamespace(exchange=exchange, timestamp=stamp, pair=pair, sequence=str(stamp) if sequence is None else sequence)

    def books(self, exchange='kucoin', stamp=None):
        return [self.book(exchange, stamp, pair) for pair in ('A-USDT','B-A','B-USDT')]

    def test_disabled_and_started_without_books_are_not_ready(self):
        self.assertEqual(self.runtime.snapshot()['reason'], 'worker_disabled')
        self.start()
        self.worker.process_books([], [])
        status = self.runtime.snapshot()
        self.assertTrue(status['thread_alive'])
        self.assertFalse(status['ready'])
        self.assertEqual(status['reason'], 'market_data_missing')
        with self.assertRaises(ValueError):
            self.runtime.start(lambda: None)

    def test_old_future_and_other_exchange_books_do_not_imply_readiness(self):
        self.start()
        self.worker.process_books([self.book('binance'), self.book(stamp=self.now + 1)], [])
        self.assertFalse(self.runtime.snapshot()['ready'])
        self.worker.process_books(self.books(stamp=self.now - 10), [])
        self.assertEqual(self.runtime.snapshot()['reason'], 'market_data_stale')
        self.worker.process_books(self.books(), [])
        self.assertTrue(self.runtime.snapshot()['ready'])
        self.now += 4
        # A fresh publish of an old book must not renew the quote's lifetime.
        self.worker.process_books([self.book(stamp=self.now - 4)], [])
        self.assertEqual(self.runtime.snapshot()['reason'], 'market_data_stale')

    def test_all_required_venues_need_current_books(self):
        self.worker.config['bots']['other'] = {'exchange': 'binance'}
        self.runtime = WorkerRuntime(self.worker, clock=lambda: self.now)
        self.start()
        self.worker.process_books(self.books(), [])
        self.assertFalse(self.runtime.snapshot()['ready'])
        self.assertTrue(self.runtime.snapshot()['bots']['bot']['ready'])
        self.worker.process_books(self.books('binance'), [])
        self.assertTrue(self.runtime.snapshot()['ready'])

    def test_processing_failure_blocks_until_success_and_never_exposes_message(self):
        self.start()
        self.worker.process_books(self.books(), [])
        self.fail_processing = True
        with self.assertRaises(ValueError):
            self.worker.process_books([self.book()], [])
        status = self.runtime.snapshot()
        self.assertEqual(status['reason'], 'processing_failed')
        self.assertEqual(status['last_error'], 'ValueError')
        self.assertNotIn('credential', str(status))
        self.fail_processing = False
        self.worker.process_books(self.books(), ['an unavailable unrelated feed'])
        self.assertTrue(self.runtime.snapshot()['ready'])
        self.assertEqual(self.runtime.snapshot()['feed_errors'], 1)

    def test_thread_failure_and_normal_exit_cannot_report_ready(self):
        def fail():
            self.worker.process_books([self.book()], [])
            raise RuntimeError('private adapter details')
        with self.assertLogs(level='ERROR') as logs:
            self.runtime.start(fail).join(timeout=2)
        status = self.runtime.snapshot()
        self.assertEqual(status['reason'], 'worker_failed')
        self.assertEqual(status['last_error'], 'RuntimeError')
        self.assertNotIn('private', str(logs.output))
        self.runtime = WorkerRuntime(self.worker, clock=lambda: self.now)
        self.runtime.start(lambda: self.worker.process_books([self.book()], [])).join(timeout=2)
        self.assertEqual(self.runtime.snapshot()['reason'], 'worker_stopped')

    def test_account_halt_and_shutdown_override_fresh_market_data(self):
        self.start()
        self.worker.process_books(self.books(), [])
        self.account['ready'] = False
        self.assertEqual(self.runtime.snapshot()['reason'], 'account_not_ready')
        self.account['ready'] = True
        self.ledger['halt'] = True
        self.assertEqual(self.runtime.snapshot()['reason'], 'trading_halted')
        self.ledger['halt'] = False
        self.worker.stop.set()
        self.assertFalse(self.runtime.snapshot()['ready'])

    def test_status_failure_and_thread_start_failure_are_reported_safely(self):
        self.start()
        self.worker.process_books(self.books(), [])
        self.worker.portfolio.snapshot = lambda: (_ for _ in ()).throw(OSError('private path'))
        self.assertEqual(self.runtime.snapshot()['reason'], 'status_unavailable')
        self.worker.stop.set()
        self.runtime.thread.join(timeout=2)
        self.runtime = WorkerRuntime(self.worker, clock=lambda: self.now)
        original = self.worker.process_books
        with patch('jin_trading.runtime.threading.Thread.start', side_effect=RuntimeError('cannot start')):
            with self.assertRaises(RuntimeError):
                self.runtime.start(lambda: None)
        self.assertEqual(self.runtime.snapshot()['reason'], 'worker_failed')
        self.assertIs(self.worker.process_books, original)

    def test_only_complete_same_venue_triangle_is_ready(self):
        self.start()
        books = self.books()
        self.worker.process_books(books[:2], [])
        self.assertEqual(self.runtime.snapshot()['bots']['bot']['complete_routes'], 0)
        self.worker.process_books([self.book(pair='C-USDT'), self.book('binance', pair='B-USDT')], [])
        self.assertFalse(self.runtime.snapshot()['ready'])
        self.worker.process_books(books[2:], [])
        self.assertTrue(self.runtime.snapshot()['ready'])
        self.assertEqual(self.runtime.snapshot()['bots']['bot']['complete_routes'], 1)

    def test_unrelated_quotes_and_duplicate_sequence_do_not_refresh_a_stale_leg(self):
        self.start()
        self.worker.process_books(self.books(), [])
        self.now += 4
        self.worker.process_books([self.book(pair='C-USDT'), self.book(pair='A-USDT', sequence='1000.0')], [])
        self.assertFalse(self.runtime.snapshot()['ready'])
        self.worker.process_books(self.books()[1:], [])
        self.assertFalse(self.runtime.snapshot()['ready'])
        self.worker.process_books([self.book()], [])
        self.assertTrue(self.runtime.snapshot()['ready'])
        self.now += 4
        self.assertFalse(self.runtime.snapshot()['ready'])

    def test_required_valuation_and_capacity_gate_complete_routes(self):
        self.worker.required_pairs = lambda exchange, signal_bot=None: ('C-USDT',)
        self.worker.universe_status = {'venues': {'kucoin': {'selected_pairs': ['A-USDT','B-A','B-USDT','C-USDT']}}}
        self.start()
        self.worker.process_books(self.books(), [])
        status = self.runtime.snapshot()['bots']['bot']
        self.assertEqual(status['missing_pairs'], ['C-USDT'])
        self.assertFalse(status['ready'])
        self.worker.process_books([self.book(pair='C-USDT')], [])
        self.assertTrue(self.runtime.snapshot()['ready'])
        self.worker.universe_status['venues']['kucoin']['capacity_exhausted'] = True
        self.assertEqual(self.runtime.snapshot()['reason'], 'capacity_exhausted')

    def test_distinct_signal_bots_have_distinct_readiness(self):
        self.worker.config['bots'] = {
            'a': {'exchange':'kucoin','strategy':'momentum','pair':'A-USDT'},
            'b': {'exchange':'kucoin','strategy':'grid','pair':'B-USDT'}}
        self.runtime = WorkerRuntime(self.worker, clock=lambda: self.now)
        self.start()
        self.worker.process_books([self.book()], [])
        status = self.runtime.snapshot()
        self.assertFalse(status['ready'])
        self.assertTrue(status['bots']['a']['ready'])
        self.assertFalse(status['bots']['b']['ready'])

    def test_future_stream_diagnostics_explain_why_a_bot_is_not_ready(self):
        self.worker.universe_status = {'venues': {'kucoin': {'future_books': 3}}}
        self.start()
        self.worker.process_books([], [])
        self.assertEqual(self.runtime.snapshot()['reason'], 'clock_skew')
        self.assertFalse(self.runtime.snapshot()['ready'])
