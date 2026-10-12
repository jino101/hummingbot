import json
import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from decimal import Decimal
from queue import Queue, Empty

from jin_trading.arbitrage import number, scan_with_diagnostics
from jin_trading.feeds import PublicFeed
from jin_trading.universe import plan_venue_batches
from jin_trading.supervisor import Portfolio
from jin_trading.execution import ExecutionEngine, PaperBroker
from jin_trading.strategies import Signals, STRATEGIES


def load_config(path):
    with open(path) as stream:
        config = json.load(stream)
    return validate_config(config)


def validate_config(config, mode='paper'):
    if config.get('mode') != mode:
        raise ValueError('Configuration mode does not match this entry point')
    if not 2 <= float(config.get('poll_seconds', 5)) <= 60:
        raise ValueError('Polling interval must be 2–60 seconds')
    if not 0 < number(config['max_deploy_fraction']) <= Decimal('0.5'):
        raise ValueError('Deployment fraction must be in (0, 0.5]')
    if not Decimal('0.002') <= number(config['stress_fraction']) <= Decimal('0.01'):
        raise ValueError('Stress assumption must be 0.2–1% per deployed amount')
    if not Decimal('0.001') <= number(config['slippage']) < 1:
        raise ValueError('Slippage buffer must be at least 0.1%')
    if not 0 < number(config['min_profit']) < 1:
        raise ValueError('Invalid profit threshold')
    if not 0 < float(config['max_age']) <= 10:
        raise ValueError('Invalid quote freshness window')
    if config.get('pair_mode', 'manual') not in ('manual', 'auto'):
        raise ValueError('Unknown pair mode')
    if config.get('pair_mode', 'manual') == 'manual' and (not config['pairs'] or len(config['pairs']) > 20):
        raise ValueError('Manual mode requires 1–20 pairs')
    for pair in config.get('pairs', []) + config.get('deny_pairs', []):
        parts = pair.split('-')
        if len(parts) != 2 or not all(parts) or parts[0] == parts[1] or pair != pair.upper():
            raise ValueError('Invalid pair format')
    batch = config.get('batch_size', 12)
    if isinstance(batch, bool) or not isinstance(batch, int) or not 3 <= batch <= 20:
        raise ValueError('Batch size must be 3–20')
    for spec in config['bots'].values():
        if spec['exchange'] not in config['fees']:
            raise ValueError('Bot exchange needs a fee assumption')
        strategy=spec.get('strategy','triangular')
        if strategy not in STRATEGIES:raise ValueError('Unknown strategy')
        if strategy in STRATEGIES[2:]:
            if not spec.get('pair'):raise ValueError('Directional strategy requires a pair')
            Signals(strategy,**spec.get('signal',{}))
        if strategy=='cross_exchange':raise ValueError('Configure cross-exchange execution through the prefunded execution API')
        if number(spec['budget'])<=0:raise ValueError('Bot budget must be positive')
    if not config['bots']:raise ValueError('At least one bot required')
    return config


class Worker:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.feeds = {ex: PublicFeed(ex, fee) for ex, fee in config['fees'].items()}
        self.stop = threading.Event()
        self.batch_indices = {}
        self._feed_events, self._feed_futures = Queue(), {}
        self.universe_status = {'mode': config.get('pair_mode', 'manual')}
        self.portfolio=Portfolio(store.path)
        self.portfolio.register(config['bots'])
        self.brokers={bot:PaperBroker(self.portfolio,bot,{},spec['budget']) for bot,spec in config['bots'].items()}
        self.engine=ExecutionEngine(self.portfolio,self.brokers,config['max_age'],number(config['slippage']),config['min_profit'])
        for bot,broker in self.brokers.items():
            try:self.store.mark_equity(bot,broker.sync())
            except ValueError:self.portfolio.invalidate_account(bot)
        self.signals={bot:Signals(spec['strategy'],**spec.get('signal',{})) for bot,spec in config['bots'].items()
                      if spec.get('strategy') in STRATEGIES[2:]}

    def required_pairs(self, exchange, signal_bot=None):
        """Keep position valuations and configured signal markets in every cycle."""
        pairs=set()
        for bot,spec in self.config['bots'].items():
            if spec['exchange']!=exchange:continue
            if spec.get('pair') and (signal_bot is None or signal_bot == bot):pairs.add(spec['pair'])
            broker=self.brokers.get(bot)
            if isinstance(broker,PaperBroker):
                pairs.update(asset+'-USDT' for asset,amount in broker.balances().items()
                             if asset!='USDT' and amount>0)
        return tuple(sorted(pairs))

    def select_venue_batch(self, exchange, pairs):
        priorities = self.required_pairs(exchange)
        plan = plan_venue_batches({exchange: pairs}, self.config.get('batch_size', 12),
                                 self.config.get('deny_pairs', ()), {exchange: priorities})[exchange]
        batches = plan.pop('batches')
        index = self.batch_indices.get(exchange, 0) % len(batches) if batches else 0
        if batches:
            self.batch_indices[exchange] = self.batch_indices.get(exchange, 0) + 1
        plan.update(batch_number=index + 1 if batches else 0,
                    selected_pairs=batches[index] if batches else (), books_received=0,
                    state='collecting' if batches else 'empty', error=None)
        return plan

    def publish_venue_status(self, exchange, status):
        """Publish actual selections; aggregates never describe a fictitious shared batch."""
        venues = dict(self.universe_status.get('venues', {}))
        venues[exchange] = dict(status)
        self.universe_status.update(venues=venues,
            catalogue_pairs={name: row['catalogue_pairs'] for name, row in venues.items()},
            scheduled_pairs=sum(row['scheduled_pairs'] for row in venues.values()),
            batch_count={name: row['batch_count'] for name, row in venues.items()},
            batch_number={name: row['batch_number'] for name, row in venues.items()},
            selected_pairs={name: row['selected_pairs'] for name, row in venues.items()},
            valuation_priority_pairs={name: row['valuation_priority_pairs'] for name, row in venues.items()})

    def tick(self):
        books, errors = [], []
        automatic = self.config.get('pair_mode', 'manual') == 'auto'
        self.universe_status.update(mode='auto' if automatic else 'manual',
            coverage='Independent bounded REST batches per exchange; not simultaneous')

        def collect(feed):
            exchange = feed.exchange
            try:
                pairs = feed.pairs() if automatic else tuple(dict.fromkeys(
                    (*self.required_pairs(exchange), *self.config['pairs'])))
                status = self.select_venue_batch(exchange, pairs)
            except Exception as exc:
                status = self.select_venue_batch(exchange, ())
                status.update(state='discovery_failed', error=type(exc).__name__)
                self._feed_events.put(('error', f'{exchange} discovery: {type(exc).__name__}'))
                self._feed_events.put(('status', (exchange, status)))
                return
            self._feed_events.put(('status', (exchange, dict(status))))
            for pair in status['selected_pairs']:
                if self.stop.is_set():
                    break
                try:
                    quote = feed.book(pair)
                    status['books_received'] += 1
                    self._feed_events.put(('book', quote))
                except Exception as exc:
                    status.update(state='feed_failed', error=type(exc).__name__)
                    self._feed_events.put(('error', f'{exchange} {pair}: {type(exc).__name__}'))
                    break  # Preserve provider cooldown; do not hammer subsequent pairs.
            if status['state'] == 'collecting':
                status['state'] = 'observed'
            self._feed_events.put(('status', (exchange, status)))

        # One in-flight task per venue, including discovery. A slow foreign venue
        # cannot prevent a healthy venue from being processed or refreshed again.
        available = [feed for name, feed in self.feeds.items()
                     if name not in self._feed_futures or self._feed_futures[name].done()]
        if available:
            pool = ThreadPoolExecutor(max_workers=len(available))
            for feed in available:
                self._feed_futures[feed.exchange] = pool.submit(collect, feed)
            pool.shutdown(wait=False)
        deadline = time.monotonic() + float(self.config['max_age'])
        while not self.stop.is_set():
            try:
                kind, value = self._feed_events.get(timeout=max(0, min(.1, deadline - time.monotonic())))
            except Empty:
                if all(f.done() for f in self._feed_futures.values()) or time.monotonic() >= deadline:
                    break
                continue
            if kind == 'status':
                self.publish_venue_status(*value)
            elif kind == 'error':
                errors.append(value)
            else:
                books.append(value)
                self.process_books(books, errors)
            if time.monotonic() >= deadline:
                break
        self.process_books(books, errors)

    def process_books(self, books, errors):
        if self.config.get("record_path"):
            from jin_trading.replay import record
            record(self.config["record_path"], books, time.time())
        for bot,broker in self.brokers.items():
            exchange=self.config['bots'][bot]['exchange']
            broker.books.update({b.pair:b for b in books if b.exchange==exchange})
            try:self.store.mark_equity(bot,broker.sync())
            except ValueError as exc:
                self.portfolio.invalidate_account(bot)
                errors=list(errors)+[bot+': '+str(exc)]
        snapshot = self.store.snapshot()
        if snapshot['halt']:self.engine.stop_all()
        denied = set(self.config.get('deny_pairs', ()))
        trading_books = [book for book in books if book.pair not in denied]
        for bot in snapshot['bots']:
            capital = number(bot['capital'])
            amount = min(capital * number(self.config['max_deploy_fraction']),
                         capital * Decimal('0.01') / number(self.config['stress_fraction']))
            opportunities, near_misses, rejected = scan_with_diagnostics(
                trading_books, amount, time.time(), max_age=self.config['max_age'],
                min_profit=number(self.config['min_profit']),
                slippage=number(self.config['slippage']), near_limit=10)
            spec = self.config['bots'][bot['id']]
            venue_status = self.universe_status.get('venues', {}).get(spec['exchange'], {})
            missing_for_bot = set(venue_status.get('missing_required_pairs', ())) & set(
                self.required_pairs(spec['exchange'], signal_bot=bot['id']))
            capacity_ready = not (venue_status.get('capacity_exhausted') or missing_for_bot or spec.get('pair') in denied)
            eligible = [o for o in opportunities if o.kind == 'triangular' and o.route[0][0] == spec['exchange']]
            bot_near = [(o, reason) for o, reason in near_misses
                        if o.kind == 'triangular' and o.route[0][0] == spec['exchange']][:5]
            # Repeat only after observing a new complete book sequence; transaction checks deduplicate.
            if bot['id'] in self.signals and bot['enabled'] and not snapshot['halt'] and capacity_ready:
                broker=self.brokers[bot['id']]
                pair=spec['pair'];book=broker.books.get(pair)
                if book and 0<=time.time()-book.timestamp<=self.config['max_age']:
                    try:
                        signal=self.signals[bot['id']].signal(book,broker.balances(),capital,broker.entry_prices())
                        if signal:self.engine.directional(bot['id'],bot['id'],pair,*signal)
                        self.store.mark_equity(bot['id'],broker.sync())
                    except ValueError as exc:errors=list(errors)+[bot['id']+': '+str(exc)]
            elif eligible and bot['enabled'] and not snapshot['halt'] and capacity_ready:
                opportunity=eligible[0]
                run_id=hashlib.sha256((bot['id']+opportunity.sequence).encode()).hexdigest()
                try:
                    result=self.engine.triangle(bot['id'],bot['id'],[pair for _,pair in opportunity.route],amount,run_id)
                    self.store.record_execution(bot['id'],opportunity,result)
                except (ValueError,KeyError) as exc:
                    if 'identifier already used' not in str(exc):errors=list(errors)+[bot['id']+': '+str(exc)]
                finally:
                    try:self.store.mark_equity(bot['id'],self.brokers[bot['id']].sync())
                    except ValueError:pass
            self.store.publish(bot['id'], {
                'feed': self.config.get('feed_label', 'REST polling'), 'books_received': len(books), 'errors': errors,
                'fee_assumptions': self.config['fees'], 'estimated_stress_loss': str(amount * number(self.config['stress_fraction'])),
                'universe': self.universe_status,
                'opportunities': [asdict(o) | {'net_fraction': str(o.net_fraction)} for o in opportunities[:20]],
                'execution': 'Sequential paper IOC; durable fills and reservations',
                'live_readiness': 'Requires local live adapter, verified account permissions and feasible route',
                'near_misses': [asdict(o) | {'net_fraction': str(o.net_fraction), 'reason': reason}
                                for o, reason in bot_near],
                'rejected_counts': rejected,
                'updated_at': time.time()})

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                logging.exception('Worker tick failed; no paper fill on failed cycle')
            self.stop.wait(float(self.config['poll_seconds']))

