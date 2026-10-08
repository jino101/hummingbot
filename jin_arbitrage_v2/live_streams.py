import asyncio
import json
import time
from dataclasses import dataclass
from typing import AsyncIterator, Dict, Optional

from .models import Quote, VenueType

@dataclass
class StreamConfig:
    venue: str
    symbol: str
    websocket_url: str
    fee_pct: float = 0.1

class WebSocketDependencyError(RuntimeError):
    pass

class JsonTickerStream:
    def __init__(self, config: StreamConfig):
        self.config = config

    async def __aiter__(self) -> AsyncIterator[Quote]:
        try:
            import websockets
        except ImportError as exc:
            raise WebSocketDependencyError(
                "Install the 'websockets' package to use live streams"
            ) from exc

        async with websockets.connect(
            self.config.websocket_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        ) as ws:
            async for raw in ws:
                data = json.loads(raw)
                quote = self.parse_message(data)
                if quote is not None:
                    yield quote

    def parse_message(self, data: Dict) -> Optional[Quote]:
        raise NotImplementedError

class BinanceBookTickerStream(JsonTickerStream):
    def __init__(self, symbol: str = "SOLUSDT", fee_pct: float = 0.1):
        lower = symbol.lower()
        super().__init__(StreamConfig(
            venue="binance",
            symbol=symbol.replace("USDT", "/USDT"),
            websocket_url=f"wss://stream.binance.com:9443/ws/{lower}@bookTicker",
            fee_pct=fee_pct,
        ))

    def parse_message(self, data: Dict) -> Optional[Quote]:
        bid = float(data.get("b", 0) or 0)
        ask = float(data.get("a", 0) or 0)
        if bid <= 0 or ask <= 0:
            return None
        return Quote(
            venue="binance",
            venue_type=VenueType.CEX,
            symbol=self.config.symbol,
            bid=bid,
            ask=ask,
            bid_size=float(data.get("B", 0) or 0),
            ask_size=float(data.get("A", 0) or 0),
            fee_pct=self.config.fee_pct,
            timestamp_ms=int(time.time() * 1000),
        )

class BybitTickerStream(JsonTickerStream):
    def __init__(self, symbol: str = "SOLUSDT", fee_pct: float = 0.1):
        super().__init__(StreamConfig(
            venue="bybit",
            symbol=symbol.replace("USDT", "/USDT"),
            websocket_url="wss://stream.bybit.com/v5/public/spot",
            fee_pct=fee_pct,
        ))
        self.raw_symbol = symbol

    async def __aiter__(self) -> AsyncIterator[Quote]:
        try:
            import websockets
        except ImportError as exc:
            raise WebSocketDependencyError(
                "Install the 'websockets' package to use live streams"
            ) from exc
        async with websockets.connect(
            self.config.websocket_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        ) as ws:
            await ws.send(json.dumps({
                "op": "subscribe",
                "args": [f"tickers.{self.raw_symbol}"],
            }))
            async for raw in ws:
                data = json.loads(raw)
                quote = self.parse_message(data)
                if quote is not None:
                    yield quote

    def parse_message(self, data: Dict) -> Optional[Quote]:
        if not str(data.get("topic", "")).startswith("tickers."):
            return None
        payload = data.get("data") or {}
        bid = float(payload.get("bid1Price", 0) or 0)
        ask = float(payload.get("ask1Price", 0) or 0)
        if bid <= 0 or ask <= 0:
            return None
        return Quote(
            venue="bybit",
            venue_type=VenueType.CEX,
            symbol=self.config.symbol,
            bid=bid,
            ask=ask,
            bid_size=float(payload.get("bid1Size", 0) or 0),
            ask_size=float(payload.get("ask1Size", 0) or 0),
            fee_pct=self.config.fee_pct,
            timestamp_ms=int(data.get("ts") or time.time() * 1000),
        )

async def merge_streams(*streams):
    """Merge streams; surface failures instead of silently waiting forever."""
    queue = asyncio.Queue(maxsize=1000)

    async def pump(stream):
        try:
            async for quote in stream:
                await queue.put(("quote", quote))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await queue.put(("error", exc))
        else:
            await queue.put(("done", None))

    tasks = [asyncio.create_task(pump(s)) for s in streams]
    remaining = len(tasks)
    try:
        while remaining:
            kind, payload = await queue.get()
            if kind == "quote":
                yield payload
            elif kind == "error":
                raise RuntimeError("Market-data stream failed") from payload
            else:
                remaining -= 1
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
