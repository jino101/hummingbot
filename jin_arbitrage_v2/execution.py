from enum import Enum
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple
from .models import Opportunity
from .risk import RiskEngine

class ExecutionState(str, Enum):
    NEW="new"; VALIDATED="validated"; SUBMITTING="submitting"; PARTIAL="partial"; FILLED="filled"; HEDGING="hedging"; FAILED="failed"; CANCELLED="cancelled"

@dataclass
class PaperLeg:
    side: str
    requested_base: float
    filled_base: float
    average_price: float
    notional_usd: float
    fee_usd: float
    complete: bool

@dataclass
class ExecutionResult:
    state: ExecutionState
    message: str
    pnl_estimate: float = 0.0
    filled_fraction: float = 0.0
    fees_usd: float = 0.0
    legs: List[PaperLeg] = field(default_factory=list)

def _walk(levels: Sequence[Sequence[float]], requested_base: float, side: str, fee_pct: float) -> PaperLeg:
    remaining = max(0.0, float(requested_base))
    filled = 0.0
    notional = 0.0
    for level in levels:
        if len(level) < 2:
            continue
        price, amount = float(level[0]), float(level[1])
        if price <= 0 or amount <= 0 or remaining <= 0:
            continue
        take = min(amount, remaining)
        filled += take
        notional += take * price
        remaining -= take
    avg = notional / filled if filled else 0.0
    fee = notional * max(0.0, float(fee_pct)) / 100.0
    return PaperLeg(side, requested_base, filled, avg, notional, fee, remaining <= 1e-12)

def simulate_two_leg_fill(op: Opportunity) -> Tuple[PaperLeg, PaperLeg, float]:
    """Deterministic, network-free two-leg paper fill from L2 snapshots in metadata."""
    buy_asks = op.metadata.get("buy_asks") or []
    sell_bids = op.metadata.get("sell_bids") or []
    buy_fee = float(op.metadata.get("buy_fee_pct", 0.0) or 0.0)
    sell_fee = float(op.metadata.get("sell_fee_pct", 0.0) or 0.0)
    if not buy_asks or not sell_bids:
        raise ValueError("paper_orderbook_missing")

    best_ask = float(buy_asks[0][0])
    if best_ask <= 0:
        raise ValueError("invalid_buy_book")
    requested_base = float(op.size_usd) / best_ask
    buy = _walk(buy_asks, requested_base, "buy", buy_fee)
    # Never paper-sell more base than the simulated buy leg obtained.
    sell = _walk(sell_bids, buy.filled_base, "sell", sell_fee)
    matched_base = min(buy.filled_base, sell.filled_base)
    if matched_base <= 0:
        return buy, sell, 0.0

    buy_cost = matched_base * buy.average_price
    sell_value = matched_base * sell.average_price
    # Allocate fees proportionally if one leg only partially matched.
    buy_fee_matched = buy.fee_usd * (matched_base / buy.filled_base) if buy.filled_base else 0.0
    sell_fee_matched = sell.fee_usd * (matched_base / sell.filled_base) if sell.filled_base else 0.0
    pnl = sell_value - buy_cost - buy_fee_matched - sell_fee_matched
    return buy, sell, pnl

class ExecutionEngine:
    def __init__(self, risk: RiskEngine, live_enabled: bool = False):
        self.risk = risk
        self.live_enabled = live_enabled

    async def execute(self, op: Opportunity) -> ExecutionResult:
        decision = self.risk.check(op)
        if not decision.approved:
            return ExecutionResult(ExecutionState.CANCELLED, decision.reason)

        if self.live_enabled:
            return ExecutionResult(
                ExecutionState.FAILED,
                "live connector execution must be implemented and validated per venue",
            )

        try:
            buy, sell, pnl = simulate_two_leg_fill(op)
        except (TypeError, ValueError):
            return ExecutionResult(ExecutionState.CANCELLED, "paper_orderbook_missing_or_invalid")

        requested_base = buy.requested_base
        matched = min(buy.filled_base, sell.filled_base)
        fraction = (matched / requested_base) if requested_base > 0 else 0.0
        fees = buy.fee_usd + sell.fee_usd

        if matched <= 0:
            return ExecutionResult(ExecutionState.CANCELLED, "paper_no_fill", 0.0, 0.0, fees, [buy, sell])

        self.risk.daily_trades += 1
        self.risk.daily_pnl += pnl

        complete = buy.complete and sell.complete and fraction >= 1.0 - 1e-12
        state = ExecutionState.FILLED if complete else ExecutionState.PARTIAL
        message = "paper_fill" if complete else "paper_partial_fill"
        return ExecutionResult(state, message, pnl, min(1.0, fraction), fees, [buy, sell])
