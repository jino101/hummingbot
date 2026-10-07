import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from decimal import Decimal

from jin_trading.arbitrage import number, scan_with_diagnostics
from jin_trading.feeds import PublicFeed
from jin_trading.universe import plan_batches


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
    return config


class Worker:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.feeds = {ex: PublicFeed(ex, fee) for ex, fee in config['fees'].items()}
        self.stop = threading.Event()
        self.batch_index = 0
        self.universe_status = {'mode': config.get('pair_mode', 'manual')}

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
        def collect(feed):
            found, failures = [], []
            for pair in selected:
                if venue_pairs and pair not in venue_pairs.get(feed.exchange, ()):
                    continue
                try:
                    found.append(feed.book(pair))
                except Exception as exc:
                    failures.append(f'{feed.exchange} {pair}: {type(exc).__name__}: {exc}')
                    # Do not hammer every remaining market during outages/rate limiting.
                    break
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
            opportunities, near_misses, rejected = scan_with_diagnostics(
                books, amount, time.time(), max_age=self.config['max_age'],
                min_profit=number(self.config['min_profit']),
                slippage=number(self.config['slippage']), near_limit=10)
            spec = self.config['bots'][bot['id']]
            eligible = [o for o in opportunities if o.kind == 'triangular' and o.route[0][0] == spec['exchange']]
            bot_near = [(o, reason) for o, reason in near_misses
                        if o.kind == 'triangular' and o.route[0][0] == spec['exchange']][:5]
            # Repeat only after observing a new complete book sequence; transaction checks deduplicate.
            if eligible:
                self.store.paper_fill(bot['id'], eligible[0])
            self.store.publish(bot['id'], {
                'feed': self.config.get('feed_label', 'REST polling'), 'books_received': len(books), 'errors': errors,
                'fee_assumptions': self.config['fees'], 'estimated_stress_loss': str(amount * number(self.config['stress_fraction'])),
                'universe': self.universe_status,
                'opportunities': [asdict(o) | {'net_fraction': str(o.net_fraction)} for o in opportunities[:20]],
                'near_misses': [asdict(o) | {'net_fraction': str(o.net_fraction), 'reason': reason}
                                for o, reason in bot_near],
                'rejected_counts': rejected,
                'live_readiness': 'Not implemented', 'updated_at': time.time()})

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                logging.exception('Worker tick failed; no paper fill on failed cycle')
            self.stop.wait(float(self.config['poll_seconds']))
