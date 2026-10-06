"""Exercise the actual executor class with an isolated base harness.

The Cython engine is unavailable here. Import nodes are omitted from its AST;
method bodies are compiled unchanged from the repository source. These regressions
supplement, but do not replace, the native Hummingbot integration tests.
"""
import ast
import asyncio
import logging
import unittest
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Union
from unittest.mock import AsyncMock, MagicMock, Mock


class Harness:
    def __init__(self, strategy, connectors, config, **kwargs):
        self.config=config;self._strategy=strategy;self.connectors=strategy.connectors
        self._status='RUNNING';self._max_retries=3;self._held_position_orders=[]
        self.close_type=None
    def stop(self):self._status='TERMINATED'
    def force_stop_with_position_hold(self):
        self._cancel_outstanding_orders()
        self._held_position_orders=self._collect_held_position_orders()
        self.close_type='POSITION_HOLD' if self._held_position_orders else 'FAILED'
        self.stop()
    @property
    def is_closed(self):return self._status=='TERMINATED'
    @property
    def net_pnl_quote(self):return self.get_net_pnl_quote()
    @property
    def cum_fees_quote(self):return self.get_cum_fees_quote()
    @property
    def status(self):return self._status
    @staticmethod
    def is_amm_connector(exchange):return False


class Tracked:
    def __init__(self):self.order_id=None;self.order=None;self.cum_fees_quote=D('0');self.average_executed_price=D('0')


def load_executor():
    filename='hummingbot/strategy_v2/executors/arbitrage_executor/arbitrage_executor.py'
    tree=ast.parse(Path(filename).read_text())
    tree.body=[node for node in tree.body if not isinstance(node,(ast.Import,ast.ImportFrom))]
    close=SimpleNamespace(COMPLETED='COMPLETED',FAILED='FAILED',POSITION_HOLD='POSITION_HOLD',INSUFFICIENT_BALANCE='INSUFFICIENT_BALANCE',EARLY_STOP='EARLY_STOP')
    namespace=dict(Decimal=D,asyncio=asyncio,logging=logging,Dict=Dict,Union=Union,ExecutorBase=Harness,
        TrackedOrder=Tracked,CloseType=close,HummingbotLogger=logging.Logger,StrategyV2Base=object,
        ArbitrageExecutorConfig=object,BuyOrderCreatedEvent=object,SellOrderCreatedEvent=object,
        MarketOrderFailureEvent=object,RateOracle=SimpleNamespace(get_instance=lambda:Mock()),
        RunnableStatus=SimpleNamespace(RUNNING='RUNNING',SHUTTING_DOWN='SHUTTING_DOWN'),
        split_hb_trading_pair=lambda pair:pair.split('-'),OrderType=SimpleNamespace(MARKET='MARKET'),
        TradeType=SimpleNamespace(BUY='BUY',SELL='SELL'))
    exec(compile(tree,filename,'exec'),namespace)
    return namespace['ArbitrageExecutor']


class ExecutorRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cls=load_executor()
        self.config=SimpleNamespace(buying_market=SimpleNamespace(connector_name='kucoin',trading_pair='ETH-USDT'),
            selling_market=SimpleNamespace(connector_name='binance',trading_pair='ETH-USDC'),
            min_profitability=D('.01'),order_amount=D('1'))
        self.strategy=MagicMock();self.strategy.connectors={}
        self.executor=self.cls(self.strategy,self.config)

    def test_pnl_denominator_and_quote_conversion(self):
        ex=self.executor;ex.close_type='COMPLETED';ex._status='TERMINATED';ex._quote_conversion_rate=D('0.5')
        ex.buy_order.order=SimpleNamespace(executed_amount_base=D('2'))
        ex.sell_order.order=SimpleNamespace(executed_amount_base=D('2'))
        ex.buy_order.average_executed_price=D('100');ex.sell_order.average_executed_price=D('210')
        ex.buy_order.cum_fees_quote=D('1');ex.sell_order.cum_fees_quote=D('2')
        self.assertEqual(ex.net_pnl_quote,D('8'))
        self.assertEqual(ex.get_net_pnl_pct(),D('0.04'))
        ex.buy_order.average_executed_price=D('0')
        self.assertEqual(ex.get_net_pnl_pct(),D('0'))

    async def test_same_quote_identity_and_invalid_oracle(self):
        ex=self.executor;ex.quote_conversion_pair='USDT-USDT'
        self.assertEqual(await ex.get_quote_asset_conversion_rate(),D('1'))
        ex.quote_conversion_pair='USDC-USDT'
        for rate in (None,D('0'),D('-1'),D('NaN')):
            ex.rate_oracle.get_pair_rate.return_value=rate
            with self.assertRaises(ValueError):await ex.get_quote_asset_conversion_rate()

    async def test_order_failure_preserves_partial_exposure_and_no_retry(self):
        ex=self.executor;ex.buy_order.order_id='buy';ex.sell_order.order_id='sell'
        ex.buy_order.order=SimpleNamespace(executed_amount_base=D('0.4'),is_done=True,to_json=lambda:{'id':'buy','filled':'0.4'})
        ex.place_buy_arbitrage_order=Mock();ex.place_sell_arbitrage_order=Mock()
        ex.process_order_failed_event(None,None,SimpleNamespace(order_id='buy'))
        ex.place_buy_arbitrage_order.assert_not_called();ex.place_sell_arbitrage_order.assert_not_called()
        self.strategy.cancel.assert_called_once_with('binance','ETH-USDC','sell')
        self.assertEqual(ex.close_type,'POSITION_HOLD')
        self.assertEqual(ex.get_custom_info()['held_position_orders'][0]['filled'],'0.4')

    async def test_submission_exception_stops_without_unknown_order_retry(self):
        ex=self.executor;ex.place_buy_arbitrage_order=Mock(side_effect=RuntimeError('rejected'))
        ex.place_sell_arbitrage_order=Mock()
        await ex.execute_arbitrage()
        self.assertEqual(ex.close_type,'FAILED');ex.place_sell_arbitrage_order.assert_not_called()

    async def test_positive_finite_quotes_and_order_amount_required(self):
        for price in (D('NaN'),D('-1'),D('0')):
            self.executor.get_buy_and_sell_prices=AsyncMock(return_value=(price,D('100')))
            with self.assertRaises(Exception):await self.executor.update_trade_pnl_pct()
        self.config.order_amount=D('0')
        with self.assertRaises(ValueError):self.cls(self.strategy,self.config)

    def test_missing_status_returns_list(self):
        self.executor._last_buy_price=D('0')
        self.assertIsInstance(self.executor.to_format_status(),list)
