import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from decimal import Decimal

from jin_trading.arbitrage import number, scan
from jin_trading.feeds import PublicFeed


def load_config(path):
    with open(path) as stream:
        config = json.load(stream)
    if config.get('mode') != 'paper':
        raise ValueError('Only paper mode is implemented; live orders are unavailable')
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
    if not config['pairs'] or len(config['pairs']) > 20:
        raise ValueError('Configure between 1 and 20 pairs')
    for spec in config['bots'].values():
        if spec['exchange'] not in config['fees']:
            raise ValueError('Bot exchange needs a fee assumption')
    return config


class Worker:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.feeds = {ex: PublicFeed(ex, fee) for ex, fee in config['fees'].items()}
        self.stop = threading.Event()

    def tick(self):
        books, errors = [], []
        # One task per exchange: refresh rules once; pairs sequentially avoid a rule-cache race.
        def collect(feed):
            found, failures = [], []
            for pair in self.config['pairs']:
                try:
                    found.append(feed.book(pair))
                except Exception as exc:
                    failures.append(f'{feed.exchange} {pair}: {type(exc).__name__}: {exc}')
            return found, failures
        with ThreadPoolExecutor(max_workers=len(self.feeds)) as pool:
            for future in as_completed([pool.submit(collect, f) for f in self.feeds.values()]):
                found, failures = future.result()
                books.extend(found)
                errors.extend(failures)
        self.process_books(books, errors)

    def process_books(self, books, errors):
        if self.config.get("record_path"):
            from jin_trading.replay import record
            record(self.config["record_path"], books, time.time())
        snapshot = self.store.snapshot()
        for bot in snapshot['bots']:
            capital = number(bot['capital'])
            amount = min(capital * number(self.config['max_deploy_fraction']),
                         capital * Decimal('0.01') / number(self.config['stress_fraction']))
            opportunities = scan(books, amount, time.time(), max_age=self.config['max_age'],
                                 min_profit=number(self.config['min_profit']),
                                 slippage=number(self.config['slippage']))
            spec = self.config['bots'][bot['id']]
            eligible = [o for o in opportunities if o.kind == 'triangular' and o.route[0][0] == spec['exchange']]
            # Repeat only after observing a new complete book sequence; transaction checks deduplicate.
            if eligible:
                self.store.paper_fill(bot['id'], eligible[0])
            self.store.publish(bot['id'], {
                'feed': self.config.get('feed_label', 'REST polling'), 'books_received': len(books), 'errors': errors,
                'fee_assumptions': self.config['fees'], 'estimated_stress_loss': str(amount * number(self.config['stress_fraction'])),
                'opportunities': [asdict(o) | {'net_fraction': str(o.net_fraction)} for o in opportunities[:20]],
                'live_readiness': 'Not implemented', 'updated_at': time.time()})

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                logging.exception('Worker tick failed; no paper fill on failed cycle')
            self.stop.wait(float(self.config['poll_seconds']))
