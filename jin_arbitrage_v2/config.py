from dataclasses import dataclass, field
from typing import List

DEFAULT_CEX = [
    "binance","bybit","okx","kucoin","gateio","mexc","bitget",
    "kraken","coinbase","bingx","bitmart","coinex","xt"
]
DEFAULT_SOLANA_DEX = ["jupiter","raydium","orca","meteora"]

@dataclass
class V2Config:
    cex: List[str] = field(default_factory=lambda: list(DEFAULT_CEX))
    solana_dex: List[str] = field(default_factory=lambda: list(DEFAULT_SOLANA_DEX))
    quotes: List[str] = field(default_factory=lambda: ["USDT","USDC","SOL"])
    min_net_profit_pct: float = 0.35
    max_price_impact_pct: float = 1.0
    max_slippage_pct: float = 0.5
    min_liquidity_usd: float = 25000.0
    max_position_usd: float = 100.0
    max_daily_loss_usd: float = 10.0
    max_daily_trades: int = 20
    paper_mode: bool = True
    live_confirmation: str = ""
    dynamic_meme_discovery: bool = True
    allow_unknown_tokens: bool = False
    blocked_mints: List[str] = field(default_factory=list)
    allowed_mints: List[str] = field(default_factory=list)

    @property
    def live_enabled(self) -> bool:
        return (not self.paper_mode) and self.live_confirmation == "I_ACCEPT_LIVE_RISK"
