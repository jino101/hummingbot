from dataclasses import dataclass
from .config import V2Config
from .models import Opportunity

@dataclass
class RiskDecision:
    approved: bool
    reason: str

class RiskEngine:
    def __init__(self, config: V2Config):
        self.config = config
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.kill_switch = False

    def check(self, op: Opportunity) -> RiskDecision:
        if self.kill_switch:
            return RiskDecision(False, "kill_switch")
        if op.net_pct < self.config.min_net_profit_pct:
            return RiskDecision(False, "profit_below_threshold")
        if op.size_usd <= 0 or op.size_usd > self.config.max_position_usd:
            return RiskDecision(False, "position_limit")
        if self.daily_trades >= self.config.max_daily_trades:
            return RiskDecision(False, "daily_trade_limit")
        if self.daily_pnl <= -abs(self.config.max_daily_loss_usd):
            return RiskDecision(False, "daily_loss_limit")
        impact = float(op.metadata.get("price_impact_pct", 0.0) or 0.0)
        if impact > self.config.max_price_impact_pct:
            return RiskDecision(False, "price_impact")
        liquidity = float(op.metadata.get("liquidity_usd", 0.0) or 0.0)
        if liquidity and liquidity < self.config.min_liquidity_usd:
            return RiskDecision(False, "low_liquidity")
        return RiskDecision(True, "approved")
