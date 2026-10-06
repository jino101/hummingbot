import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from hummingbot.strategy.strategy_v2_base import StrategyV2ConfigBase


def test_runtime_loader_uses_jino_config_class_not_imported_base():
    config = {
        "controller_type": "generic",
        "controller_name": "jino_cross_exchange_arbitrage",
        "id": "runtime-loader-test",
        "manual_kill_switch": False,
        "exchange_pair_1": {
            "connector_name": "binance_paper_trade",
            "trading_pair": "BTC-USDT",
        },
        "exchange_pair_2": {
            "connector_name": "kucoin_paper_trade",
            "trading_pair": "BTC-USDT",
        },
        "min_profitability": "0.005",
        "delay_between_executors": 10,
        "max_executors_imbalance": 1,
        "rate_connector": "binance_paper_trade",
        "quote_conversion_asset": "USDT",
        "total_amount_quote": "25",
        "safety_mode": "paper",
        "max_trade_amount_quote": "25",
        "max_daily_loss_quote": "25",
        "max_completed_trades_per_day": 100,
    }

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conf_jino_runtime_loader.yml"
        path.write_text(yaml.safe_dump(config, sort_keys=False))
        runner = StrategyV2ConfigBase(controllers_config=[path.name])

        with patch("hummingbot.strategy.strategy_v2_base.settings.CONTROLLERS_CONF_DIR_PATH", Path(tmp)):
            loaded = runner.load_controller_configs()

    assert len(loaded) == 1
    loaded_config = loaded[0]
    assert loaded_config.__class__.__name__ == "JinoCrossExchangeArbitrageConfig"
    assert loaded_config.rate_connector == "binance_paper_trade"
    assert loaded_config.max_completed_trades_per_day == 100
