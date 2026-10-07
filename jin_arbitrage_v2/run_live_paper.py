import asyncio

from .config import V2Config
from .execution import ExecutionEngine
from .hft_engine import FastArbitrageEngine
from .live_streams import BinanceBookTickerStream, BybitTickerStream, merge_streams
from .risk import RiskEngine

async def main():
    config = V2Config()
    risk = RiskEngine(config)
    executor = ExecutionEngine(risk, live_enabled=False)
    engine = FastArbitrageEngine(executor, size_usd=25.0, min_interval_ms=100)

    print("JIN V2 LIVE MARKET PAPER TEST")
    print("LIVE ORDERS: OFF")
    print("Streams: Binance + Bybit SOL/USDT")

    streams = merge_streams(
        BinanceBookTickerStream("SOLUSDT"),
        BybitTickerStream("SOLUSDT"),
    )
    count = 0
    async for quote in streams:
        count += 1
        result = await engine.on_quote(quote)
        if count % 20 == 0:
            print(
                f"{quote.venue:8} {quote.symbol:10} "
                f"bid={quote.bid:.6f} ask={quote.ask:.6f} "
                f"paper_trades={risk.daily_trades}"
            )
        if result is not None:
            print(
                f"PAPER EXECUTION state={result.state.value} "
                f"estimated_pnl={result.pnl_estimate:.6f}"
            )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
