from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
from .models import Quote, VenueType

@dataclass
class SolanaToken:
    symbol: str
    mint: str
    decimals: int = 9
    liquidity_usd: float = 0.0
    verified: bool = False

class SolanaTokenFilter:
    def __init__(self, blocked_mints=None, allowed_mints=None, min_liquidity_usd=25000.0, allow_unknown=False):
        self.blocked = set(blocked_mints or [])
        self.allowed = set(allowed_mints or [])
        self.min_liquidity_usd = min_liquidity_usd
        self.allow_unknown = allow_unknown

    def accepts(self, token: SolanaToken) -> bool:
        if token.mint in self.blocked:
            return False
        if self.allowed and token.mint not in self.allowed:
            return False
        if token.liquidity_usd < self.min_liquidity_usd:
            return False
        if not token.verified and not self.allow_unknown:
            return False
        return True

class SolanaDexAdapter:
    name = "base"
    async def discover_tokens(self) -> List[SolanaToken]:
        return []
    async def quote(self, input_mint: str, output_mint: str, amount: int) -> Optional[Quote]:
        raise NotImplementedError

class JupiterAdapter(SolanaDexAdapter):
    name = "jupiter"

class RaydiumAdapter(SolanaDexAdapter):
    name = "raydium"

class OrcaAdapter(SolanaDexAdapter):
    name = "orca"

class MeteoraAdapter(SolanaDexAdapter):
    name = "meteora"

def normalize_dex_quote(venue: str, symbol: str, bid: float, ask: float, *, mint=None, liquidity_usd=None, price_impact_pct=None, fee_pct=0.0, timestamp_ms=0) -> Quote:
    return Quote(venue=venue, venue_type=VenueType.DEX, symbol=symbol, bid=bid, ask=ask, fee_pct=fee_pct, timestamp_ms=timestamp_ms, token_mint=mint, liquidity_usd=liquidity_usd, price_impact_pct=price_impact_pct)
