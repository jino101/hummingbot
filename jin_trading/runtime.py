"""In-process worker supervision and readiness based on observed market data."""
import logging
import math
import threading
import time
from functools import wraps
from jin_trading.universe import route_groups


class WorkerRuntime:
    """Track a worker without confusing an HTTP listener with a healthy feed.

    Market timestamps come from successfully processed books, never the ledger's
    publish time. A running thread and a fresh cash-only account are insufficient.
    Exception messages are deliberately excluded because adapters may include
    credentials or request URLs in them.
    """

    def __init__(self, worker=None, clock=time.time):
        self.worker, self.clock = worker, clock
        self.lock = threading.RLock()
        self.thread = None
        self.enabled = False
        self.state = 'disabled'
        self.started_at = self.stopped_at = self.processed_at = None
        self.last_error = None
        self.feed_errors = self.processed_batches = 0
        self.market_times = {}
        self.books = {}
        self.max_age = float(worker.config['max_age']) if worker else 0
        self.exchanges = sorted({spec['exchange'] for spec in worker.config['bots'].values()}) if worker else []

    def start(self, target):
        with self.lock:
            if self.worker is None:
                raise ValueError('Worker unavailable')
            if self.enabled:
                raise ValueError('Worker runtime already started')
            self.enabled = True
            self.state = 'starting'
            original = self.worker.process_books

            @wraps(original)
            def observed(books, errors):
                try:
                    result = original(books, errors)
                except Exception as exc:
                    with self.lock:
                        self.last_error = type(exc).__name__
                    raise
                with self.lock:
                    self.processed_at = self.clock()
                    self.processed_batches += 1
                    self.feed_errors = len(errors)
                    self.last_error = None
                    for book in books:
                        stamp = float(book.timestamp)
                        if book.exchange in self.exchanges and math.isfinite(stamp) and 0 <= self.processed_at - stamp:
                            key = (book.exchange, book.pair)
                            previous = self.books.get(key)
                            if previous and (str(previous.sequence) == str(book.sequence) or stamp < previous.timestamp):
                                continue
                            self.books[key] = book
                            self.market_times[book.exchange] = max(stamp, self.market_times.get(book.exchange, stamp))
                return result

            self.worker.process_books = observed

            def run():
                with self.lock:
                    self.state = 'running'
                    self.started_at = self.clock()
                try:
                    target()
                except Exception as exc:
                    with self.lock:
                        self.state = 'failed'
                        self.last_error = type(exc).__name__
                    logging.error('Worker terminated: %s', type(exc).__name__)
                finally:
                    with self.lock:
                        if self.state != 'failed':
                            self.state = 'stopped'
                        self.stopped_at = self.clock()
                    self.worker.process_books = original

            self.thread = threading.Thread(target=run, name='jin-market-worker', daemon=True)
            try:
                self.thread.start()
            except Exception as exc:
                self.worker.process_books = original
                self.state = 'failed'
                self.last_error = type(exc).__name__
                self.stopped_at = self.clock()
                raise
            return self.thread

    def bot_status(self, bot_id, spec, now):
        """Market completeness is separate from profitability and order minimums."""
        exchange = spec['exchange']
        known = {pair: book for (venue, pair), book in self.books.items() if venue == exchange}
        fresh = {pair for pair, book in known.items() if 0 <= now - book.timestamp <= self.max_age}
        denied = set(self.worker.config.get('deny_pairs', ()))
        venue = getattr(self.worker, 'universe_status', {}).get('venues', {}).get(exchange, {})
        expected = set(venue.get('selected_pairs', ()))
        required = set(self.worker.required_pairs(exchange, signal_bot=bot_id))
        strategy = spec.get('strategy', 'triangular')
        groups = [group for group in route_groups(set(known) - denied) if len(group) == 3]
        complete = [group for group in groups if set(group) <= fresh]
        if strategy != 'triangular':
            required.add(spec['pair'])
            complete = [(spec['pair'],)] if spec['pair'] in fresh - denied else []
        expected.update(required)
        if not expected:
            expected.update(known)
        missing = sorted(expected - set(known))
        stale = sorted(expected.intersection(known) - fresh)
        reason = 'ready'
        if venue.get('capacity_exhausted'):
            reason = 'capacity_exhausted'
        elif required - fresh:
            reason = 'market_data_stale' if required.intersection(known) - fresh else 'market_data_missing'
        elif not complete:
            reason = ('clock_skew' if venue.get('future_books') else
                      'market_data_stale' if groups else ('route_incomplete' if known else 'market_data_missing'))
        route_time = max((min(known[p].timestamp for p in group) for group in complete), default=None)
        return {'ready': reason == 'ready', 'reason': reason, 'complete_routes': len(complete),
                'missing_pairs': missing, 'stale_pairs': stale, 'last_route_at': route_time,
                'route_age_seconds': now - route_time if route_time is not None else None}

    def snapshot(self):
        now = self.clock()
        with self.lock:
            alive = bool(self.thread and self.thread.is_alive())
            markets = {}
            for exchange in self.exchanges:
                stamp = self.market_times.get(exchange)
                age = now - stamp if stamp is not None else None
                markets[exchange] = {'last_market_at': stamp, 'age_seconds': age,
                                     'fresh': age is not None and 0 <= age <= self.max_age}
            reason = 'ready'
            if not self.enabled:
                reason = 'worker_disabled'
            elif self.state == 'failed':
                reason = 'worker_failed'
            elif self.state == 'starting':
                reason = 'worker_starting'
            elif not alive or self.state != 'running':
                reason = 'worker_stopped'
            elif self.worker.stop.is_set():
                reason = 'worker_stopping'
            elif self.last_error:
                reason = 'processing_failed'
            bots = {name: self.bot_status(name, spec, now) for name, spec in self.worker.config['bots'].items()} if self.worker else {}
            if reason != 'ready':
                for bot in bots.values():
                    bot.update(ready=False, reason=reason)
            elif not bots:
                reason = 'market_data_missing'
            else:
                reason = next((bot['reason'] for bot in bots.values() if not bot['ready']), 'ready')
            result = {'enabled': self.enabled, 'state': self.state, 'thread_alive': alive,
                      'ready': reason == 'ready', 'reason': reason, 'last_error': self.last_error,
                      'started_at': self.started_at, 'stopped_at': self.stopped_at,
                      'last_processed_at': self.processed_at, 'processed_batches': self.processed_batches,
                      'feed_errors': self.feed_errors, 'max_market_age_seconds': self.max_age,
                      'markets': markets, 'bots': bots}
        if self.worker and self.enabled and alive and self.state == 'running' and not self.worker.stop.is_set():
            try:
                portfolio = self.worker.portfolio.snapshot()
                halted = self.worker.store.snapshot()['halt']
                if halted or portfolio['halt']:
                    block = 'trading_halted'
                elif not portfolio['ready']:
                    block = 'account_not_ready'
                else:
                    block = None
                if block:
                    result.update(ready=False, reason=block)
                    for bot in bots.values():
                        bot.update(ready=False, reason=block)
            except Exception as exc:
                result.update(ready=False, reason='status_unavailable', last_error=type(exc).__name__)
                for bot in bots.values():
                    bot.update(ready=False, reason='status_unavailable')
        return result


def start_worker(server, target):
    """Start either REST or WebSocket execution under the same monitor."""
    if server.runtime.worker is not server.worker:
        server.runtime = WorkerRuntime(server.worker)
    return server.runtime.start(target)
