"""Single conservative cost model shared by scanners."""
from dataclasses import dataclass

@dataclass(frozen=True)
class CostModel:
    buy_fee_pct: float = 0.1
    sell_fee_pct: float = 0.1
    slippage_pct: float = 0.0
    price_impact_pct: float = 0.0
    transfer_cost_usd: float = 0.0
    network_cost_usd: float = 0.0

    def pct_for_size(self, size_usd: float) -> float:
        if size_usd <= 0:
            raise ValueError("size_usd_must_be_positive")
        fixed = max(0.0, self.transfer_cost_usd) + max(0.0, self.network_cost_usd)
        return (max(0.0,self.buy_fee_pct)+max(0.0,self.sell_fee_pct)+
                max(0.0,self.slippage_pct)+max(0.0,self.price_impact_pct)+
                fixed/size_usd*100.0)

    def net_pct(self, gross_pct: float, size_usd: float) -> float:
        return float(gross_pct) - self.pct_for_size(size_usd)
