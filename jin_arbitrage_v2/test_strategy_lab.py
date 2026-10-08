import unittest
from .strategy_lab import mean_reversion,momentum,breakout,grid_levels,market_making_quote,pairs_zscore,simple_backtest
from .advanced_arbitrage import scan_cycle,funding_arbitrage,cash_and_carry
from .analysis_lab import portfolio_metrics,rank_yields,liquidation_pressure,anomaly_score,onchain_flow

class StrategyLabTests(unittest.TestCase):
    def test_signals(self):
        self.assertEqual(momentum([100]*20+[102],20,1).side,"buy")
        self.assertEqual(breakout(list(range(100,121)),20).side,"buy")
        self.assertEqual(len(grid_levels(100,1,3)),3)
        bid,ask=market_making_quote(100); self.assertLess(bid,ask)
        self.assertIsNotNone(pairs_zscore(list(range(100,140)),list(range(50,90)),30))
    def test_multi_leg(self):
        rates={("USD","A"):2,("A","B"):1,("B","C"):1,("C","USD"):0.51}
        r=scan_cycle(rates,["USD","A","B","C","USD"],0,25); self.assertGreater(r.net_pct,0)
        self.assertIsNotNone(funding_arbitrage(100,101,0.1))
        self.assertIsNotNone(cash_and_carry(100,105,30))
    def test_analytics(self):
        self.assertIn("max_drawdown",portfolio_metrics([.01,-.02,.03]))
        self.assertEqual(rank_yields([{"apy":5,"tvl_usd":200000}])[0]["apy"],5)
        self.assertGreater(liquidation_pressure([{"side":"long","usd":2},{"side":"short","usd":1}])["imbalance"],0)
        self.assertGreater(anomaly_score(20,[1,2,3,4,5]),0)
        self.assertEqual(onchain_flow([{"direction":"in","usd":3},{"direction":"out","usd":1}])["net_flow_usd"],2)
    def test_backtest(self):
        out=simple_backtest([100]*20+[102,103,104],lambda x: momentum(x,20,.5)); self.assertIn("pnl",out)

if __name__=="__main__":unittest.main()
