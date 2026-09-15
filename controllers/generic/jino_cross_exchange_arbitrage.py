from decimal import Decimal
from typing import List, Literal

from pydantic import Field, field_validator, model_validator

from controllers.generic.arbitrage_controller import ArbitrageController, ArbitrageControllerConfig
from hummingbot.strategy_v2.executors.data_types import ConnectorPair
from hummingbot.strategy_v2.models.executor_actions import ExecutorAction


class JinoCrossExchangeArbitrageConfig(ArbitrageControllerConfig):
    """Safety-first cross-exchange arbitrage configuration.

    The controller deliberately defaults to paper-trade connectors. Switching to real
    connectors requires setting ``safety_mode`` to ``live`` explicitly.
    """

    controller_name: str = "jino_cross_exchange_arbitrage"
    exchange_pair_1: ConnectorPair = ConnectorPair(
        connector_name="binance_paper_trade",
        trading_pair="BTC-USDT",
    )
    exchange_pair_2: ConnectorPair = ConnectorPair(
        connector_name="kucoin_paper_trade",
        trading_pair="BTC-USDT",
    )
    min_profitability: Decimal = Field(default=Decimal("0.005"), ge=Decimal("0"))
    delay_between_executors: int = Field(default=10, ge=0)
    max_executors_imbalance: int = Field(default=1, ge=1)
    rate_connector: str = "binance"
    quote_conversion_asset: str = "USDT"

    safety_mode: Literal["paper", "live"] = "paper"
    max_trade_amount_quote: Decimal = Field(default=Decimal("100"), gt=Decimal("0"))
    max_daily_loss_quote: Decimal = Field(default=Decimal("25"), ge=Decimal("0"))
    max_completed_trades_per_day: int = Field(default=100, ge=1)

    @field_validator("exchange_pair_1", "exchange_pair_2")
    @classmethod
    def validate_pair_format(cls, value: ConnectorPair) -> ConnectorPair:
        if "-" not in value.trading_pair:
            raise ValueError("trading_pair must use Hummingbot BASE-QUOTE format, e.g. BTC-USDT")
        return value

    @model_validator(mode="after")
    def validate_safety_limits(self):
        if self.total_amount_quote <= 0:
            raise ValueError("total_amount_quote must be greater than zero")
        if self.total_amount_quote > self.max_trade_amount_quote:
            raise ValueError(
                "total_amount_quote cannot exceed max_trade_amount_quote; "
                "raise the cap explicitly if you really want a larger trade"
            )

        connectors = [self.exchange_pair_1.connector_name, self.exchange_pair_2.connector_name]
        if self.safety_mode == "paper":
            live_connectors = [name for name in connectors if not name.endswith("_paper_trade")]
            if live_connectors:
                raise ValueError(
                    "safety_mode=paper only accepts *_paper_trade connectors. "
                    f"Live connector(s) supplied: {', '.join(live_connectors)}"
                )
        return self


class JinoCrossExchangeArbitrageController(ArbitrageController):
    """Arbitrage controller with hard safety gates around Hummingbot's ArbitrageExecutor.

    Hummingbot's executor performs amount-aware quote requests on both venues and includes
    transaction/trading fees in its profitability calculation. This wrapper adds explicit
    paper/live separation, a per-trade quote cap, a UTC daily loss limit, a completed-trade
    limit, and honors the base manual kill switch before creating any new executor.
    """

    config: JinoCrossExchangeArbitrageConfig

    def __init__(self, config: JinoCrossExchangeArbitrageConfig, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config

    def _completed_executors_today(self):
        now = self.market_data_provider.time()
        utc_day_start = now - (now % 86400)
        return [
            executor
            for executor in self.executors_info
            if executor.close_timestamp is not None and executor.close_timestamp >= utc_day_start
        ]

    def _daily_realized_pnl_quote(self) -> Decimal:
        return sum(
            (executor.net_pnl_quote for executor in self._completed_executors_today()),
            Decimal("0"),
        )

    def _risk_gate_reason(self) -> str:
        if self.config.manual_kill_switch:
            return "manual kill switch is enabled"

        completed_today = self._completed_executors_today()
        if len(completed_today) >= self.config.max_completed_trades_per_day:
            return "daily completed-trade limit reached"

        if self.config.max_daily_loss_quote > 0:
            realized_pnl = self._daily_realized_pnl_quote()
            if realized_pnl <= -self.config.max_daily_loss_quote:
                return "daily realized-loss limit reached"

        return ""

    def determine_executor_actions(self) -> List[ExecutorAction]:
        reason = self._risk_gate_reason()
        if reason:
            self.logger().warning(f"Jino arbitrage safety gate: {reason}. No new executor will be created.")
            return []
        return super().determine_executor_actions()

    def to_format_status(self) -> List[str]:
        parent_lines = super().to_format_status()
        lines = list(parent_lines) if parent_lines else []
        reason = self._risk_gate_reason() or "clear"
        lines.append(
            "Jino safety: "
            f"mode={self.config.safety_mode} | "
            f"trade_cap={self.config.max_trade_amount_quote} {self.config.quote_conversion_asset} | "
            f"daily_pnl={self._daily_realized_pnl_quote()} {self.config.quote_conversion_asset} | "
            f"gate={reason}"
        )
        return lines
