"""Bridge conservative L2 scanner candidates into the risk/paper execution model.

Paper/read-only only: this module contains no exchange order submission path.
"""
from .models import Opportunity, StrategyType

def depth_candidate_to_opportunity(candidate, books):
    buy = next((b for b in books if b.venue == candidate["buy"] and b.symbol == candidate["symbol"]), None)
    sell = next((b for b in books if b.venue == candidate["sell"] and b.symbol == candidate["symbol"]), None)
    if buy is None or sell is None:
        raise ValueError("candidate_book_missing")

    return Opportunity(
        strategy=StrategyType.CROSS_EXCHANGE,
        buy_venue=buy.venue,
        sell_venue=sell.venue,
        symbol=buy.symbol,
        gross_pct=float(candidate["gross_pct"]),
        net_pct=float(candidate["estimated_net_pct"]),
        size_usd=float(candidate["size_usd"]),
        estimated_profit_usd=float(candidate["estimated_profit_usd"]),
        metadata={
            "buy_asks": [list(x) for x in buy.asks],
            "sell_bids": [list(x) for x in sell.bids],
            "buy_fee_pct": float(buy.fee_pct),
            "sell_fee_pct": float(sell.fee_pct),
            "scanner_base_qty": float(candidate.get("base_qty", 0.0) or 0.0),
            "source": "depth_scanner",
        },
    )

async def execute_depth_candidates(candidates, books, executor, limit=1):
    results = []
    for candidate in list(candidates)[:max(0, int(limit))]:
        op = depth_candidate_to_opportunity(candidate, books)
        result = await executor.execute(op)
        results.append((op, result))
    return results
