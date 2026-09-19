from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from controllers.generic.jino_cross_exchange_arbitrage import (
    JinoCrossExchangeArbitrageConfig,
    JinoCrossExchangeArbitrageController,
)
from hummingbot.strategy_v2.executors.data_types import ConnectorPair
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo
from hummingbot.strategy_v2.executors.arbitrage_executor.data_types import ArbitrageExecutorConfig


def make_controller(config: JinoCrossExchangeArbitrageConfig):
    provider = MagicMock()
    provider.time.return_value = 2 * 86400 + 3600
    provider.initialize_rate_sources.return_value = None
    provider.get_rate.return_value = Decimal("100")
    controller = JinoCrossExchangeArbitrageController(config, provider, MagicMock())
    return controller


def make_executor_info(pnl: Decimal, close_timestamp: float):
    config = ArbitrageExecutorConfig(
        timestamp=close_timestamp - 10,
        buying_market=ConnectorPair(connector_name="binance_paper_trade", trading_pair="BTC-USDT"),
        selling_market=ConnectorPair(connector_name="kucoin_paper_trade", trading_pair="BTC-USDT"),
        order_amount=Decimal("0.001"),
        min_profitability=Decimal("0.005"),
    )
    return ExecutorInfo(
        id="executor-1",
        timestamp=close_timestamp - 10,
        type="arbitrage_executor",
        status=RunnableStatus.TERMINATED,
        config=config,
        net_pnl_pct=Decimal("0"),
        net_pnl_quote=pnl,
        cum_fees_quote=Decimal("0"),
        filled_amount_quote=Decimal("0"),
        is_active=False,
        is_trading=False,
        custom_info={},
        close_timestamp=close_timestamp,
    )


def test_defaults_are_paper_only():
    config = JinoCrossExchangeArbitrageConfig(id="test")
    assert config.safety_mode == "paper"
    assert config.exchange_pair_1.connector_name.endswith("_paper_trade")
    assert config.exchange_pair_2.connector_name.endswith("_paper_trade")
    assert config.rate_connector == "binance_paper_trade"


def test_paper_mode_rejects_live_connector():
    with pytest.raises(ValueError):
        JinoCrossExchangeArbitrageConfig(
            id="test",
            exchange_pair_1=ConnectorPair(connector_name="binance", trading_pair="BTC-USDT"),
        )


def test_trade_cap_is_enforced():
    with pytest.raises(ValueError):
        JinoCrossExchangeArbitrageConfig(
            id="test",
            total_amount_quote=Decimal("101"),
            max_trade_amount_quote=Decimal("100"),
        )


def test_manual_kill_switch_blocks_new_actions():
    config = JinoCrossExchangeArbitrageConfig(id="test", manual_kill_switch=True)
    controller = make_controller(config)
    assert controller.determine_executor_actions() == []


def test_daily_loss_limit_blocks_new_actions():
    config = JinoCrossExchangeArbitrageConfig(id="test", max_daily_loss_quote=Decimal("25"))
    controller = make_controller(config)
    now = controller.market_data_provider.time()
    controller.executors_info = [make_executor_info(Decimal("-30"), now - 60)]
    assert controller.determine_executor_actions() == []


def test_old_loss_does_not_count_toward_current_day():
    config = JinoCrossExchangeArbitrageConfig(id="test", max_daily_loss_quote=Decimal("25"))
    controller = make_controller(config)
    now = controller.market_data_provider.time()
    controller.executors_info = [make_executor_info(Decimal("-30"), now - 90000)]
    assert controller._daily_realized_pnl_quote() == Decimal("0")


def test_live_mode_rejects_paper_connectors():
    with pytest.raises(ValueError):
        JinoCrossExchangeArbitrageConfig(
            id="test",
            safety_mode="live",
            exchange_pair_1=ConnectorPair(connector_name="binance_paper_trade", trading_pair="BTC-USDT"),
            exchange_pair_2=ConnectorPair(connector_name="kucoin", trading_pair="BTC-USDT"),
            rate_connector="kucoin",
        )


def test_rejects_same_exchange_on_both_legs():
    with pytest.raises(ValueError):
        JinoCrossExchangeArbitrageConfig(
            id="test",
            exchange_pair_1=ConnectorPair(connector_name="binance_paper_trade", trading_pair="BTC-USDT"),
            exchange_pair_2=ConnectorPair(connector_name="binance_paper_trade", trading_pair="BTC-USDT"),
        )


def test_rejects_mismatched_base_assets():
    with pytest.raises(ValueError):
        JinoCrossExchangeArbitrageConfig(
            id="test",
            exchange_pair_1=ConnectorPair(connector_name="binance_paper_trade", trading_pair="BTC-USDT"),
            exchange_pair_2=ConnectorPair(connector_name="kucoin_paper_trade", trading_pair="ETH-USDT"),
        )


def test_custom_info_exposes_safety_state():
    config = JinoCrossExchangeArbitrageConfig(id="test")
    controller = make_controller(config)
    info = controller.get_custom_info()
    assert info["strategy"] == "jino_cross_exchange_arbitrage"
    assert info["safety_mode"] == "paper"
    assert info["risk_gate"] == "clear"
    assert info["completed_trades_today"] == 0


def test_clear_risk_gate_proposes_both_arbitrage_directions():
    config = JinoCrossExchangeArbitrageConfig(
        id="test",
        total_amount_quote=Decimal("25"),
        max_trade_amount_quote=Decimal("25"),
    )
    controller = make_controller(config)
    controller.market_data_provider.quantize_order_amount.return_value = Decimal("0.001")
    actions = controller.determine_executor_actions()
    assert len(actions) == 2
    directions = {
        (
            action.executor_config.buying_market.connector_name,
            action.executor_config.selling_market.connector_name,
        )
        for action in actions
    }
    assert directions == {
        ("binance_paper_trade", "kucoin_paper_trade"),
        ("kucoin_paper_trade", "binance_paper_trade"),
    }
    assert all(action.executor_config.order_amount == Decimal("0.001") for action in actions)


def test_completed_trade_limit_blocks_new_actions():
    config = JinoCrossExchangeArbitrageConfig(id="test", max_completed_trades_per_day=1)
    controller = make_controller(config)
    now = controller.market_data_provider.time()
    controller.executors_info = [make_executor_info(Decimal("1"), now - 60)]
    assert controller.determine_executor_actions() == []


def test_config_resolves_jino_controller_class_not_imported_parent():
    config = JinoCrossExchangeArbitrageConfig(id="test")
    controller_class = config.get_controller_class()
    assert controller_class is JinoCrossExchangeArbitrageController
