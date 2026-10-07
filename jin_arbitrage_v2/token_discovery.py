from dataclasses import dataclass
from typing import Iterable,List
from .solana import SolanaToken,SolanaTokenFilter

def filter_discovered_tokens(tokens:Iterable[SolanaToken], token_filter:SolanaTokenFilter, limit=500)->List[SolanaToken]:
    accepted=[t for t in tokens if token_filter.accepts(t)]
    accepted.sort(key=lambda t:t.liquidity_usd,reverse=True)
    return accepted[:limit]
