import unittest
from .config import V2Config
from .execution import ExecutionEngine, ExecutionState, simulate_two_leg_fill
from .models import Opportunity, StrategyType
from .risk import RiskEngine

def make_op(size=100.0, buy=None, sell=None, buy_fee=.1, sell_fee=.1):
    return Opportunity(
        strategy=StrategyType.CROSS_EXCHANGE,
        buy_venue="buy", sell_venue="sell", symbol="SOL/USDT",
        gross_pct=2.0, net_pct=1.0, size_usd=size, estimated_profit_usd=1.0,
        metadata={
            "buy_asks": buy or [[100.0, 2.0]],
            "sell_bids": sell or [[102.0, 2.0]],
            "buy_fee_pct": buy_fee, "sell_fee_pct": sell_fee,
            "liquidity_usd": 100000.0,
        },
    )

class TestPaperExecution(unittest.IsolatedAsyncioTestCase):
    async def test_full_fill_uses_depth_and_fees(self):
        risk = RiskEngine(V2Config(max_position_usd=200))
        result = await ExecutionEngine(risk).execute(make_op())
        self.assertEqual(result.state, ExecutionState.FILLED)
        self.assertAlmostEqual(result.filled_fraction, 1.0)
        self.assertGreater(result.pnl_estimate, 0)
        self.assertGreater(result.fees_usd, 0)
        self.assertEqual(risk.daily_trades, 1)
        self.assertAlmostEqual(risk.daily_pnl, result.pnl_estimate)

    async def test_partial_buy_depth_is_reported(self):
        risk = RiskEngine(V2Config(max_position_usd=200))
        result = await ExecutionEngine(risk).execute(
            make_op(buy=[[100.0, .4]], sell=[[102.0, 2.0]])
        )
        self.assertEqual(result.state, ExecutionState.PARTIAL)
        self.assertAlmostEqual(result.filled_fraction, .4)

    async def test_partial_sell_depth_is_reported(self):
        risk = RiskEngine(V2Config(max_position_usd=200))
        result = await ExecutionEngine(risk).execute(
            make_op(buy=[[100.0, 2.0]], sell=[[102.0, .25]])
        )
        self.assertEqual(result.state, ExecutionState.PARTIAL)
        self.assertAlmostEqual(result.filled_fraction, .25)

    async def test_risk_limit_blocks_before_fill(self):
        risk = RiskEngine(V2Config(max_position_usd=50))
        result = await ExecutionEngine(risk).execute(make_op(size=100))
        self.assertEqual(result.state, ExecutionState.CANCELLED)
        self.assertEqual(result.message, "position_limit")
        self.assertEqual(risk.daily_trades, 0)

    async def test_kill_switch_blocks(self):
        risk = RiskEngine(V2Config(max_position_usd=200))
        risk.kill_switch = True
        result = await ExecutionEngine(risk).execute(make_op())
        self.assertEqual(result.state, ExecutionState.CANCELLED)
        self.assertEqual(result.message, "kill_switch")

    async def test_missing_book_never_fakes_fill(self):
        op = make_op()
        op.metadata["buy_asks"] = []
        risk = RiskEngine(V2Config(max_position_usd=200))
        result = await ExecutionEngine(risk).execute(op)
        self.assertEqual(result.state, ExecutionState.CANCELLED)
        self.assertEqual(result.message, "paper_orderbook_missing_or_invalid")
        self.assertEqual(risk.daily_trades, 0)

    def test_direct_simulation_is_deterministic(self):
        op = make_op()
        a = simulate_two_leg_fill(op)
        b = simulate_two_leg_fill(op)
        self.assertEqual(a, b)

if __name__ == "__main__":
    unittest.main()
