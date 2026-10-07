from typing import Iterable, List
from .models import Quote, Opportunity, StrategyType

def cross_venue_opportunities(quotes: Iterable[Quote], size_usd: float = 25.0, slippage_pct: float = 0.0) -> List[Opportunity]:
    qs = list(quotes)
    out: List[Opportunity] = []
    for buy in qs:
        for sell in qs:
            if buy.venue == sell.venue or buy.symbol != sell.symbol or buy.ask <= 0:
                continue
            gross_pct = (sell.bid / buy.ask - 1.0) * 100.0
            fees = buy.fee_pct + sell.fee_pct
            impact = max(float(buy.price_impact_pct or 0), float(sell.price_impact_pct or 0))
            net_pct = gross_pct - fees - slippage_pct - impact
            if net_pct <= 0:
                continue
            if buy.venue_type.value == "dex" and sell.venue_type.value == "dex":
                strategy = StrategyType.DEX_TO_DEX
            elif buy.venue_type != sell.venue_type:
                strategy = StrategyType.CEX_TO_DEX
            else:
                strategy = StrategyType.CROSS_EXCHANGE
            liqs = [x for x in [buy.liquidity_usd, sell.liquidity_usd] if x is not None]
            out.append(Opportunity(
                strategy=strategy,
                buy_venue=buy.venue,
                sell_venue=sell.venue,
                symbol=buy.symbol,
                gross_pct=gross_pct,
                net_pct=net_pct,
                size_usd=size_usd,
                estimated_profit_usd=size_usd * net_pct / 100.0,
                metadata={"price_impact_pct": impact, "liquidity_usd": min(liqs) if liqs else 0.0}
            ))
    out.sort(key=lambda x: x.net_pct, reverse=True)
    return out
