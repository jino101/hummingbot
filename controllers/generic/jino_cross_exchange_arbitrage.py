from decimal import Decimal
from typing import List, Literal

from pydantic import Field, field_validator, model_validator

from controllers.generic.arbitrage_controller import ArbitrageController, ArbitrageControllerConfig
from hummingbot.strategy_v2.executors.data_types import ConnectorPair
from hummingbot.strategy_v2.models.executor_actions import ExecutorAction
from hummingbot.jino_arbitrage.live_checks import collect_live_readiness, collect_observation_readiness
from hummingbot.jino_arbitrage.runtime_scanner import scan_provider_pair_for_quote_amount
from hummingbot.jino_arbitrage.scanner import ScannerPolicy


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
    rate_connector: str = "binance_paper_trade"
    quote_conversion_asset: str = "USDT"

    safety_mode: Literal["paper", "observe", "live"] = "paper"
    max_trade_amount_quote: Decimal = Field(default=Decimal("100"), gt=Decimal("0"))
    max_daily_loss_quote: Decimal = Field(default=Decimal("25"), ge=Decimal("0"))
    max_completed_trades_per_day: int = Field(default=100, ge=1)
    paper_test_force_execution: bool = False
    live_readiness_max_age_seconds: int = Field(default=120, ge=10, le=3600)
    observe_min_net_spread_pct: Decimal = Field(default=Decimal("0"), ge=Decimal("-1"))
    observe_estimated_slippage_pct: Decimal = Field(default=Decimal("0.001"), ge=Decimal("0"))
    observe_log_path: str = "data/jino_observations.jsonl"
    observe_latest_path: str = "data/jino_observe_latest.json"
    runtime_kill_switch_path: str = "data/jino_kill_switch"

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

        connectors = [
            self.exchange_pair_1.connector_name,
            self.exchange_pair_2.connector_name,
            self.rate_connector,
        ]

        if self.exchange_pair_1.connector_name == self.exchange_pair_2.connector_name:
            raise ValueError("cross-exchange arbitrage requires two different exchange connectors")

        base_1 = self.exchange_pair_1.trading_pair.split("-")[0]
        base_2 = self.exchange_pair_2.trading_pair.split("-")[0]
        if base_1 != base_2:
            raise ValueError("both exchange pairs must share the same base asset")

        if self.safety_mode in {"paper", "observe"}:
            live_connectors = [name for name in connectors if not name.endswith("_paper_trade")]
            if live_connectors:
                mode_note = "paper mode" if self.safety_mode == "paper" else "credential-free observe mode"
                raise ValueError(
                    f"{mode_note} only accepts *_paper_trade connectors, including rate_connector. "
                    f"Live connector(s) supplied: {', '.join(live_connectors)}"
                )
        else:
            paper_connectors = [name for name in connectors if name.endswith("_paper_trade")]
            if paper_connectors:
                raise ValueError(
                    f"safety_mode={self.safety_mode} cannot use *_paper_trade connectors. "
                    f"Paper connector(s) supplied: {', '.join(paper_connectors)}"
                )

        if self.safety_mode != "paper" and self.paper_test_force_execution:
            raise ValueError("paper_test_force_execution is only allowed in safety_mode=paper")
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
        self._last_live_readiness_probe_at = 0.0

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
        if Path(self.config.runtime_kill_switch_path).exists():
            return "runtime kill switch file is present"

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

    async def update_processed_data(self):
        if self.config.safety_mode == "paper":
            self.processed_data["live_readiness"] = None
            self.processed_data["observation_readiness"] = None
            return

        now = self.market_data_provider.time()
        current = (
            self.processed_data.get("observation_readiness")
            if self.config.safety_mode in {"observe", "readonly"}
            else self.processed_data.get("live_readiness")
        )
        probe_interval = min(30.0, max(10.0, self.config.live_readiness_max_age_seconds / 2))
        if current and now - self._last_live_readiness_probe_at < probe_interval:
            return

        connector_names = [
            self.config.exchange_pair_1.connector_name,
            self.config.exchange_pair_2.connector_name,
        ]

        if self.config.safety_mode in {"observe", "readonly"}:
            try:
                report = await collect_observation_readiness(
                    market_data_provider=self.market_data_provider,
                    connector_names=connector_names,
                    trading_pair=self.config.exchange_pair_1.trading_pair,
                    total_amount_quote=self.config.total_amount_quote,
                    quote_conversion_asset=self.config.quote_conversion_asset,
                    max_age_seconds=self.config.live_readiness_max_age_seconds,
                )
                self._last_live_readiness_probe_at = now
                self.processed_data["observation_readiness"] = {
                    "safe_read_only": report.safe_read_only,
                    "credential_free": report.credential_free,
                    "market_data_ready": report.market_data_ready,
                    "account_data_verified": report.account_data_verified,
                    "transfer_route_verified": report.transfer_route_verified,
                    "hypothetical_trade_feasible": report.hypothetical_trade_feasible,
                    "reasons": report.reasons,
                    "common_rebalance_networks": report.common_rebalance_networks,
                    "transfer_estimates": tuple(
                        {
                            "network": item.network,
                            "estimated_minutes": (
                                None if item.estimated_minutes is None else str(item.estimated_minutes)
                            ),
                            "source": item.source,
                        }
                        for item in report.transfer_estimates
                    ),
                    "checked_at": report.checked_at,
                }

                network_map = {
                    snapshot.exchange: list(snapshot.networks)
                    for snapshot in report.network_snapshots
                }
                opportunities = scan_provider_pair_for_quote_amount(
                    market_data_provider=self.market_data_provider,
                    connector_names=connector_names,
                    trading_pair=self.config.exchange_pair_1.trading_pair,
                    quote_amount=self.config.total_amount_quote,
                    policy=ScannerPolicy(
                        min_net_spread_pct=self.config.observe_min_net_spread_pct,
                        estimated_slippage_pct=self.config.observe_estimated_slippage_pct,
                        require_rebalance_transferable=not report.credential_free,
                        max_quote_age_seconds=self.config.live_readiness_max_age_seconds,
                    ),
                    networks=network_map,
                )
                self.processed_data["observation_opportunities"] = tuple(
                    {
                        "trading_pair": item.trading_pair,
                        "buy_exchange": item.buy_exchange,
                        "sell_exchange": item.sell_exchange,
                        "amount_base": str(item.amount_base),
                        "buy_price": str(item.buy_price),
                        "sell_price": str(item.sell_price),
                        "gross_spread_pct": str(item.gross_spread_pct),
                        "estimated_fee_pct": str(item.estimated_fee_pct),
                        "estimated_slippage_pct": str(item.estimated_slippage_pct),
                        "net_spread_pct": str(item.net_spread_pct),
                        "expected_profit_quote": str(item.expected_profit_quote),
                        "rebalance_fee_quote": str(item.estimated_rebalance_fee_quote),
                        "expected_profit_after_rebalance_quote": str(
                            item.expected_profit_after_rebalance_quote
                        ),
                        "common_transfer_networks": tuple(item.common_transfer_networks),
                    }
                    for item in opportunities[:10]
                )
            self._persist_observation()
            except Exception as exc:
                self._last_live_readiness_probe_at = now
                self.logger().error(f"Jino observation probe failed: {exc}")
                self.processed_data["observation_readiness"] = {
                    "safe_read_only": False,
                    "credential_free": True,
                    "market_data_ready": False,
                    "account_data_verified": False,
                    "transfer_route_verified": False,
                    "hypothetical_trade_feasible": False,
                    "reasons": (f"observation probe failed: {exc}",),
                    "common_rebalance_networks": (),
                    "transfer_estimates": (),
                }
                self.processed_data["observation_opportunities"] = ()
            self.processed_data["live_readiness"] = None
            self._persist_observation()
            return
        if self.config.exchange_pair_1.trading_pair != self.config.exchange_pair_2.trading_pair:
            self.processed_data["live_readiness"] = {
                "ready": False,
                "reasons": ("live readiness requires identical trading pairs on both exchanges",),
                "common_rebalance_networks": (),
            }
            return

        try:
            report = await collect_live_readiness(
                market_data_provider=self.market_data_provider,
                connector_names=connector_names,
                trading_pair=self.config.exchange_pair_1.trading_pair,
                total_amount_quote=self.config.total_amount_quote,
                quote_conversion_asset=self.config.quote_conversion_asset,
                max_age_seconds=self.config.live_readiness_max_age_seconds,
            )
            self._last_live_readiness_probe_at = now
            self.processed_data["live_readiness"] = {
                "ready": report.ready,
                "reasons": report.reasons,
                "common_rebalance_networks": report.common_rebalance_networks,
                "checked_at": report.checked_at,
            }
        except Exception as exc:
            self._last_live_readiness_probe_at = now
            self.logger().error(f"Jino live-readiness probe failed: {exc}")
            self.processed_data["live_readiness"] = {
                "ready": False,
                "reasons": (f"live-readiness probe failed: {exc}",),
                "common_rebalance_networks": (),
            }

    def _persist_observation(self) -> None:
        readiness = self.processed_data.get("observation_readiness") or {}
        snapshot = {
            "timestamp": self.market_data_provider.time(),
            "mode": self.config.safety_mode,
            "trading_pair": self.config.exchange_pair_1.trading_pair,
            "exchange_1": self.config.exchange_pair_1.connector_name,
            "exchange_2": self.config.exchange_pair_2.connector_name,
            "quote_amount": str(self.config.total_amount_quote),
            "readiness": readiness,
            "opportunities": list(self.processed_data.get("observation_opportunities") or ()),
            "executors": 0,
            "positions": 0,
            "runtime_kill_switch": Path(self.config.runtime_kill_switch_path).exists(),
        }
        try:
            persist_observation_snapshot(
                self.config.observe_log_path,
                self.config.observe_latest_path,
                snapshot,
            )
        except Exception as exc:
            self.logger().warning(f"Jino observation persistence failed: {exc}")

    def _live_readiness_gate_reason(self) -> str:
        if self.config.safety_mode != "live":
            return ""
        report = self.processed_data.get("live_readiness")
        if not report:
            return "live readiness has not been verified"
        if report.get("ready") is not True:
            reasons = report.get("reasons") or ("live readiness failed",)
            return "live readiness failed: " + "; ".join(str(reason) for reason in reasons)
        return ""

    def determine_executor_actions(self) -> List[ExecutorAction]:
        if self.config.safety_mode in {"observe", "readonly"}:
            # Hard no-trade modes: analysis is allowed, executor/order creation is not.
            return []

        live_reason = self._live_readiness_gate_reason()
        if live_reason:
            self.logger().warning(f"Jino arbitrage live gate: {live_reason}. No executor will be created.")
            return []

        reason = self._risk_gate_reason()
        if reason:
            self.logger().warning(f"Jino arbitrage safety gate: {reason}. No new executor will be created.")
            return []

        actions = super().determine_executor_actions()
        if self.config.paper_test_force_execution and actions:
            # Deterministic execution-path validation only: create one direction, once.
            # The dedicated paper test sets max_completed_trades_per_day=1 so the risk
            # gate blocks any further executor after this one completes.
            return actions[:1]
        return actions

    def create_arbitrage_executor_action(self, buying_exchange_pair, selling_exchange_pair):
        action = super().create_arbitrage_executor_action(buying_exchange_pair, selling_exchange_pair)
        if action is not None:
            action.executor_config.one_leg_recovery_enabled = True
            # Automatic third-order hedging stays disabled. One-leg/partial-fill exposure
            # is preserved and escalated rather than silently adding another live order.
            action.executor_config.auto_hedge_enabled = False

        if action is not None and self.config.paper_test_force_execution:
            # A deliberately negative threshold guarantees the paper executor reaches
            # the order-placement path once valid quotes/fees are available. This is
            # never accepted in live safety mode.
            action.executor_config.min_profitability = Decimal("-1")
        return action

    def get_custom_info(self) -> dict:
        completed_today = self._completed_executors_today()
        return {
            "strategy": "jino_cross_exchange_arbitrage",
            "safety_mode": self.config.safety_mode,
            "exchange_1": self.config.exchange_pair_1.connector_name,
            "exchange_2": self.config.exchange_pair_2.connector_name,
            "trading_pair_1": self.config.exchange_pair_1.trading_pair,
            "trading_pair_2": self.config.exchange_pair_2.trading_pair,
            "min_profitability": str(self.config.min_profitability),
            "trade_cap_quote": str(self.config.max_trade_amount_quote),
            "daily_loss_cap_quote": str(self.config.max_daily_loss_quote),
            "completed_trades_today": len(completed_today),
            "completed_trade_limit": self.config.max_completed_trades_per_day,
            "daily_realized_pnl_quote": str(self._daily_realized_pnl_quote()),
            "risk_gate": self._risk_gate_reason() or "clear",
            "paper_test_force_execution": self.config.paper_test_force_execution,
            "live_readiness": self.processed_data.get("live_readiness"),
            "observation_readiness": self.processed_data.get("observation_readiness"),
            "observation_opportunities": self.processed_data.get("observation_opportunities", ()),
        }

    def to_format_status(self) -> List[str]:
        parent_lines = super().to_format_status()
        lines = list(parent_lines) if parent_lines else []
        info = self.get_custom_info()
        lines.append(
            "Jino safety: "
            f"mode={info['safety_mode']} | "
            f"trade_cap={info['trade_cap_quote']} {self.config.quote_conversion_asset} | "
            f"daily_pnl={info['daily_realized_pnl_quote']} {self.config.quote_conversion_asset} | "
            f"completed={info['completed_trades_today']}/{info['completed_trade_limit']} | "
            f"gate={info['risk_gate']} | "
            f"live_ready={None if info['live_readiness'] is None else info['live_readiness'].get('ready')} | "
            f"market_ready={None if info['observation_readiness'] is None else info['observation_readiness'].get('market_data_ready')} | "
            f"transfer_verified={None if info['observation_readiness'] is None else info['observation_readiness'].get('transfer_route_verified')} | "
            f"observe_opps={len(info['observation_opportunities'])}"
        )

        if info["safety_mode"] == "observe" and info["observation_readiness"]:
            obs = info["observation_readiness"]
            estimates = obs.get("transfer_estimates") or ()
            if estimates:
                eta_text = ", ".join(
                    f"{item['network']}="
                    f"{item['estimated_minutes'] if item['estimated_minutes'] is not None else '?'}m"
                    for item in estimates
                )
                lines.append(f"Jino observed transfer ETA: {eta_text}")

            if info["observation_opportunities"]:
                best = info["observation_opportunities"][0]
                lines.append(
                    "Jino best hypothetical trade (NO ORDER): "
                    f"{best['trading_pair']} buy={best['buy_exchange']} @{best['buy_price']} | "
                    f"sell={best['sell_exchange']} @{best['sell_price']} | "
                    f"net={best['net_spread_pct']} | "
                    f"after_rebalance={best['expected_profit_after_rebalance_quote']} "
                    f"{self.config.quote_conversion_asset}"
                )
            elif obs.get("reasons"):
                lines.append("Jino observe notes: " + "; ".join(str(x) for x in obs["reasons"][:3]))
        return lines
