"""WebSocket-data bridge to the JIN paper ledger. This script submits NO orders."""
import os
import time
from pathlib import Path
from typing import List

from pydantic import Field

from hummingbot.core.data_type.common import MarketDict
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase
from jin_trading.arbitrage import Book, number
from jin_trading.store import Store
from jin_trading.worker import Worker, load_config


class JinArbitrageMonitorConfig(StrategyV2ConfigBase):
    script_file_name: str = os.path.basename(__file__)
    controllers_config: List[str] = []
    jin_config_path: str = Field(default='jin_trading/config.example.json')
    jin_db_path: str = Field(default='data/jin-paper.sqlite')
    scan_interval: float = Field(default=1.0, ge=0.2, le=60)

    def update_markets(self, markets: MarketDict) -> MarketDict:
        config = load_config(self.jin_config_path)
        for exchange in config['fees']:
            markets[exchange] = markets.get(exchange, set()) | set(config['pairs'])
        return markets


class JinArbitrageMonitor(StrategyV2Base):
    def __init__(self, connectors, config):
        # The bridge must remain observation-only; controllers could otherwise submit live orders.
        if config.controllers_config:
            raise ValueError('Controllers are not allowed in this read-only bridge')
        super().__init__(connectors, config)
        self.config = config
        settings = load_config(config.jin_config_path)
        settings['feed_label'] = 'Hummingbot WebSocket books (paper estimates)'
        Path(config.jin_db_path).parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(config.jin_db_path)
        self.store.configure({bot: spec['budget'] for bot, spec in settings['bots'].items()})
        self.worker = Worker(self.store, settings)
        self.next_scan = 0

    def on_tick(self):
        if self.current_timestamp < self.next_scan:
            return
        self.next_scan = self.current_timestamp + self.config.scan_interval
        books, errors = [], []
        for exchange, connector in self.connectors.items():
            for pair in self.worker.config['pairs']:
                try:
                    if not connector.ready:
                        raise ValueError('Connector not ready')
                    rule = connector.trading_rules[pair]
                    if not rule.supports_market_orders:
                        raise ValueError('Market orders not supported')
                    book = connector.get_order_book(pair)
                    metrics = connector.order_book_tracker.metrics.per_pair_metrics[pair]
                    last = max(metrics.last_diff_timestamp, metrics.last_snapshot_timestamp)
                    if last <= 0:
                        raise ValueError('No book freshness telemetry')
                    stamp = time.time() - (time.perf_counter() - last)
                    bids = tuple((number(row.price), number(row.amount)) for row in book.bid_entries())[:100]
                    asks = tuple((number(row.price), number(row.amount)) for row in book.ask_entries())[:100]
                    books.append(Book(exchange, pair, bids, asks, stamp, str(book.snapshot_uid) + ':' + str(book.last_diff_uid),
                                      number(self.worker.config['fees'][exchange]), number(rule.min_base_amount_increment),
                                      number(rule.min_order_size), max(number(rule.min_notional_size), number(rule.min_order_value)),
                                      number(rule.max_order_size)))
                except Exception as exc:
                    errors.append(f'{exchange} {pair}: {type(exc).__name__}: {exc}')
        self.worker.process_books(books, errors)

    def to_format_status(self):
        snapshot = self.store.snapshot()
        return [f"JIN PAPER — virtual equity {snapshot['capital']} USDT; halt={snapshot['halt']}",
                'No live orders. Dashboard uses the same SQLite ledger.']
