"""One-shot multi-exchange orderbook scan, read-only / paper candidates only."""
import argparse
import time
from .depth_scanner import DEFAULT_EXCHANGES, fetch_public_books, scan_depth_books

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--venues",default=",".join(DEFAULT_EXCHANGES))
    p.add_argument("--symbols",default="SOL/USDT,BTC/USDT")
    p.add_argument("--size",type=float,default=25.)
    p.add_argument("--max-age-ms",type=int,default=30000)
    a=p.parse_args()
    venues=[v.strip() for v in a.venues.split(",") if v.strip()]
    symbols=[s.strip() for s in a.symbols.split(",") if s.strip()]
    print("JIN V2 – public read-only orderbook scan; ORDERS DISABLED",flush=True)
    books,errors=fetch_public_books(venues,symbols)
    for book in books:
        print(f"{book.venue:10} {book.symbol:12} bid={book.bids[0][0]:.6f} ask={book.asks[0][0]:.6f}")
    for key,message in errors.items():
        print(f"FEED_ERROR {key}: {message}")
    results=scan_depth_books(books,size_usd=a.size,max_age_ms=a.max_age_ms)
    print(f"books={len(books)} errors={len(errors)} paper_candidates={len(results)}")
    for result in results[:20]:
        print(f"PAPER_CANDIDATE {result['symbol']} {result['buy']} -> {result['sell']} "
              f"estimated_net={result['estimated_net_pct']:.3f}% "
              f"estimated_usd={result['estimated_profit_usd']:.4f}")
    print("Estimates only: no synchronized books, verified account fees, transfers or live fills.")

if __name__=="__main__":
    main()
