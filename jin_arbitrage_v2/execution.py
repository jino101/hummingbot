from enum import Enum
from dataclasses import dataclass
from .models import Opportunity
from .risk import RiskEngine

class ExecutionState(str, Enum):
    NEW="new"; VALIDATED="validated"; SUBMITTING="submitting"; PARTIAL="partial"; FILLED="filled"; HEDGING="hedging"; FAILED="failed"; CANCELLED="cancelled"

@dataclass
class ExecutionResult:
    state: ExecutionState
    message: str
    pnl_estimate: float = 0.0

class ExecutionEngine:
    def __init__(self, risk: RiskEngine, live_enabled: bool = False):
        self.risk = risk
        self.live_enabled = live_enabled

    async def execute(self, op: Opportunity) -> ExecutionResult:
        decision = self.risk.check(op)
        if not decision.approved:
            return ExecutionResult(ExecutionState.CANCELLED, decision.reason)
        if not self.live_enabled:
            self.risk.daily_trades += 1
            self.risk.daily_pnl += op.estimated_profit_usd
            return ExecutionResult(ExecutionState.FILLED, "paper_fill", op.estimated_profit_usd)
        return ExecutionResult(ExecutionState.FAILED, "live connector execution must be implemented and validated per venue")
