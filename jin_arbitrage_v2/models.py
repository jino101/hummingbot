from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List

class VenueType(str, Enum):
    CEX = "cex"
    DEX = "dex"

class StrategyType(str, Enum):
    CROSS_EXCHANGE = "cross_exchange"
    TRIANGULAR = "triangular"
    DEX_TO_DEX = "dex_to_dex"
    CEX_TO_DEX = "cex_to_dex"

@dataclass
class Quote:
    venue: str
    venue_type: VenueType
    symbol: str
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    fee_pct: float = 0.0
    timestamp_ms: int = 0
    token_mint: Optional[str] = None
    liquidity_usd: Optional[float] = None
    price_impact_pct: Optional[float] = None

@dataclass
class Opportunity:
    strategy: StrategyType
    buy_venue: str
    sell_venue: str
    symbol: str
    gross_pct: float
    net_pct: float
    size_usd: float
    estimated_profit_usd: float
    route: List[str] = field(default_factory=list)
    risk_score: float = 0.0
    metadata: dict = field(default_factory=dict)
