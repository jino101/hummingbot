import unittest
from .solana import SolanaToken,SolanaTokenFilter,normalize_dex_quote
from .token_discovery import filter_discovered_tokens

class SolanaTests(unittest.TestCase):
    def test_token_filter(self):
        f=SolanaTokenFilter(min_liquidity_usd=1000)
        good=SolanaToken("GOOD","mint1",9,2000,True)
        bad=SolanaToken("BAD","mint2",9,100,True)
        self.assertEqual(filter_discovered_tokens([bad,good],f),[good])
    def test_unknown_fails_closed(self):
        f=SolanaTokenFilter(min_liquidity_usd=1,allow_unknown=False)
        self.assertFalse(f.accepts(SolanaToken("X","x",9,100,False)))
    def test_quote_normalization(self):
        q=normalize_dex_quote("jupiter","SOL/USDC",99,100,mint="m",liquidity_usd=100000,price_impact_pct=.1)
        self.assertEqual(q.venue,"jupiter"); self.assertEqual(q.ask,100)

if __name__=="__main__":unittest.main()
