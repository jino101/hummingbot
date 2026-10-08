"""Hummingbot Gateway client for Solana/EVM DEX quotes.

Compatible with Gateway's parameterized trading routes. Execution stays opt-in.
"""
import json
from urllib import request, parse

class GatewayClient:
    def __init__(self, base_url="http://localhost:15888", timeout=10):
        self.base_url=base_url.rstrip("/"); self.timeout=timeout
    def _get(self,path,params):
        url=self.base_url+path+"?"+parse.urlencode(params)
        with request.urlopen(url,timeout=self.timeout) as r:
            return json.loads(r.read().decode())
    def quote_router(self, connector, chain_network, base, quote, amount, side="BUY"):
        return self._get("/trading/router/quote-swap",{
            "connector":connector,"chainNetwork":chain_network,
            "baseToken":base,"quoteToken":quote,"amount":amount,"side":side})
    def chain_status(self, chain):
        return self._get(f"/chains/{chain}/status",{})
    def estimate_gas(self, chain):
        return self._get(f"/chains/{chain}/estimate-gas",{})
