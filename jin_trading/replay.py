"""Record/replay public snapshots. This is not a queue/latency execution backtest."""
import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from jin_trading.arbitrage import Book, number, scan
from jin_trading.store import Store
from jin_trading.worker import load_config


def record(path, books, now, max_bytes=10_000_000):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > max_bytes:
        path.replace(path.with_suffix(path.suffix + '.1'))
    with path.open('a') as stream:
        stream.write(json.dumps({'timestamp': now, 'books': [asdict(b) for b in books]}, default=str, allow_nan=False) + '\n')


def decode_book(value):
    data = dict(value)
    for key in ('fee', 'step', 'min_size', 'min_notional', 'max_size'):
        data[key] = number(data[key])
    for key in ('bids', 'asks'):
        data[key] = tuple((number(p), number(q)) for p, q in data[key])
    return Book(**data)


def replay(path, config, db_path):
    if Path(db_path).exists():
        raise ValueError('Replay requires a new ledger; cannot overwrite an existing account')
    store = Store(db_path)
    store.configure({bot: spec['budget'] for bot, spec in config['bots'].items()})
    for bot in config['bots']:
        store.control(bot, True)
    last, events = 0, 0
    with open(path) as stream:
        for line in stream:
            if len(line) > 4_000_000:
                raise ValueError('Replay record too large')
            event = json.loads(line)
            stamp = float(number(event['timestamp']))
            if stamp < last:
                raise ValueError('Replay timestamps must be ordered')
            last = stamp
            books = [decode_book(b) for b in event['books']]
            for bot, spec in config['bots'].items():
                with store.connect() as db:
                    capital = number(db.execute('SELECT capital FROM bots WHERE id=?', (bot,)).fetchone()[0])
                amount = min(capital * number(config['max_deploy_fraction']),
                             capital * Decimal('0.01') / number(config['stress_fraction']))
                opportunities = scan(books, amount, stamp, max_age=config['max_age'],
                                     min_profit=number(config['min_profit']), slippage=number(config['slippage']))
                eligible = [o for o in opportunities if o.kind == 'triangular' and o.route[0][0] == spec['exchange']]
                if eligible:
                    store.paper_fill(bot, eligible[0], now=stamp)
            events += 1
    with store.connect() as db:
        return {'events': events, 'paper_trades': db.execute('SELECT COUNT(*) FROM trades').fetchone()[0],
                'paper_equity': str(store._total(db)), 'model': 'instant depth estimate, no real orders'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('recording')
    parser.add_argument('--config', default='jin_trading/config.example.json')
    parser.add_argument('--db', required=True, help='New replay database path')
    args = parser.parse_args()
    print(json.dumps(replay(args.recording, load_config(args.config), args.db), indent=2))


if __name__ == '__main__':
    main()
