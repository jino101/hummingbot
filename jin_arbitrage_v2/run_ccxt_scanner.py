"""Read-only multi-exchange CCXT scanner. No order execution."""
import argparse
from .ccxt_feed import fetch_public_quotes
from .opportunity import cross_venue_opportunities

def main():
    parser=argparse.ArgumentParser(description="Public market scanner only")
    parser.add_argument("--venues",default="kraken,kucoin,bitget")
    parser.add_argument("--symbols",default="BTC/USDT,SOL/USDT")
    parser.add_argument("--min-net",type=float,default=0.35)
    parser.add_argument("--max-age-ms",type=int,default=5000)
    args=parser.parse_args()
    venues=[v.strip() for v in args.venues.split(",") if v.strip()]
    symbols=[s.strip() for s in args.symbols.split(",") if s.strip()]
    quotes,errors=fetch_public_quotes(venues,symbols)
    import time
    now=int(time.time()*1000)
    fresh=[q for q in quotes if 0 <= now-q.timestamp_ms <= args.max_age_ms]
    print(f"Valid quotes: {len(quotes)}, fresh: {len(fresh)}, errors: {len(errors)}")
    for q in fresh:
        print(f"{q.venue:10} {q.symbol:12} bid={q.bid:.8f} ask={q.ask:.8f}")
    for k,v in errors.items():
        print(f"FEED_ERROR {k}: {v}")
    for symbol in symbols:
        opportunities=cross_venue_opportunities(
            [q for q in fresh if q.symbol==symbol],size_usd=25.0,
            slippage_pct=0.15)
        for op in opportunities:
            if op.net_pct>=args.min_net:
                print(f"PAPER_CANDIDATE {op.symbol} buy={op.buy_venue} sell={op.sell_venue} net_est={op.net_pct:.3f}%")
    print("READ-ONLY: No orders sent. Sizes, depth and fees not yet fully verified.")

if __name__=="__main__":
    main()
