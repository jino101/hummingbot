import unittest, tempfile, os
from .config import V2Config
from .risk import RiskEngine
from .execution import ExecutionEngine
from .models import Opportunity,StrategyType
from .persistence import TradeStore
from .rebalancer import plan_rebalance
from .dashboard_schema import status_payload

class AllBlocksAcceptance(unittest.IsolatedAsyncioTestCase):
    async def test_paper_risk_execution_persistence_dashboard(self):
        cfg=V2Config(min_net_profit_pct=.1,max_position_usd=100)
        risk=RiskEngine(cfg); engine=ExecutionEngine(risk)
        op=Opportunity(StrategyType.CROSS_EXCHANGE,"a","b","SOL/USDT",2,1,25,.25,metadata={
            "buy_asks":[[100,1]],"sell_bids":[[102,1]],"buy_fee_pct":.1,"sell_fee_pct":.1})
        result=await engine.execute(op)
        self.assertEqual(result.state.value,"filled")
        fd,path=tempfile.mkstemp(); os.close(fd)
        try:
            store=TradeStore(path); store.record(op,result.state.value)
            self.assertEqual(store.summary()["trades"],1)
        finally:
            os.unlink(path)
        payload=status_payload(cfg,risk,[op]); self.assertEqual(payload["mode"],"PAPER")
    def test_rebalance(self):
        acts=plan_rebalance({"x":{"USDT":50}},{"x":{"USDT":100}})
        self.assertEqual(len(acts),1)

if __name__=="__main__":unittest.main()
