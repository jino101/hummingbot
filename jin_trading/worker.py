import json
import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from decimal import Decimal
from queue import Queue, Empty

from jin_trading.arbitrage import number, scan_with_diagnostics
from jin_trading.feeds import PublicFeed
from jin_trading.universe import plan_batches
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
        self.batch_index = 0
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

    def tick(self):
        books, errors = [], []
        venue_pairs = {}
        if self.config.get('pair_mode', 'manual') == 'auto':
            def discover(feed):
                try:
                    return feed.exchange, feed.pairs(), None
                except Exception as exc:
                    return feed.exchange, (), f'{feed.exchange} discovery: {type(exc).__name__}: {exc}'
            with ThreadPoolExecutor(max_workers=len(self.feeds)) as pool:
                for exchange, pairs, failure in pool.map(discover, self.feeds.values()):
                    venue_pairs[exchange] = pairs
                    if failure:
                        errors.append(failure)
            batches = plan_batches(venue_pairs, self.config.get('batch_size', 12), self.config.get('deny_pairs', []))
            index = self.batch_index % len(batches) if batches else 0
            selected = batches[index] if batches else ()
            self.batch_index += 1
            self.universe_status = {'mode': 'auto', 'catalogue_pairs': {ex: len(p) for ex, p in venue_pairs.items()},
                                    'scheduled_pairs': len({p for batch in batches for p in batch}),
                                    'batch_count': len(batches), 'batch_number': index + 1 if batches else 0,
                                    'selected_pairs': selected, 'coverage': 'Rotating REST batches; not simultaneous'}
        else:
            selected = self.config['pairs']
        # One task per exchange: refresh rules once; pairs sequentially avoid a rule-cache race.
        queue=Queue()
        def collect(feed):
            for pair in selected:
                if venue_pairs and pair not in venue_pairs.get(feed.exchange, ()):
                    continue
                try:
                    queue.put(('book',feed.book(pair)))
                except Exception as exc:
                    queue.put(('error',f'{feed.exchange} {pair}: {type(exc).__name__}: {exc}'))
                    # Do not hammer every remaining market during outages/rate limiting.
                    break
            queue.put(('done',feed.exchange))
        with ThreadPoolExecutor(max_workers=len(self.feeds)) as pool:
            futures=[pool.submit(collect, f) for f in self.feeds.values()]
            done=0
            while done<len(futures):
                try:kind,value=queue.get(timeout=1)
                except Empty:
                    if all(f.done() for f in futures):
                        for f in futures:f.result()
                        break
                    continue
                if kind=='done':done+=1
                elif kind=='error':errors.append(value)
                else:
                    books.append(value)
                    # A slow venue cannot delay an already complete fresh route.
                    self.process_books(books,errors)
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
        for bot in snapshot['bots']:
            capital = number(bot['capital'])
            amount = min(capital * number(self.config['max_deploy_fraction']),
                         capital * Decimal('0.01') / number(self.config['stress_fraction']))
            opportunities, near_misses, rejected = scan_with_diagnostics(
                books, amount, time.time(), max_age=self.config['max_age'],
                min_profit=number(self.config['min_profit']),
                slippage=number(self.config['slippage']), near_limit=10)
            spec = self.config['bots'][bot['id']]
            eligible = [o for o in opportunities if o.kind == 'triangular' and o.route[0][0] == spec['exchange']]
            bot_near = [(o, reason) for o, reason in near_misses
                        if o.kind == 'triangular' and o.route[0][0] == spec['exchange']][:5]
            # Repeat only after observing a new complete book sequence; transaction checks deduplicate.
            if bot['id'] in self.signals and bot['enabled'] and not snapshot['halt']:
                broker=self.brokers[bot['id']]
                pair=spec['pair'];book=broker.books.get(pair)
                if book and 0<=time.time()-book.timestamp<=self.config['max_age']:
                    try:
                        signal=self.signals[bot['id']].signal(book,broker.balances(),capital,broker.entry_prices())
                        if signal:self.engine.directional(bot['id'],bot['id'],pair,*signal)
                        self.store.mark_equity(bot['id'],broker.sync())
                    except ValueError as exc:errors=list(errors)+[bot['id']+': '+str(exc)]
            elif eligible and bot['enabled'] and not snapshot['halt']:
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
