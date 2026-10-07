"""Low-latency/event-driven arbitrage orchestration.

This is retail/API HFT-like execution, not colocated institutional HFT.
"""
import asyncio, time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional
from .models import Quote
from .opportunity import cross_venue_opportunities

@dataclass
class LatencyStats:
    last_ms: float = 0.0
    samples: int = 0
    avg_ms: float = 0.0
    def add(self, value: float):
        self.last_ms=value; self.samples+=1
        self.avg_ms += (value-self.avg_ms)/self.samples

class OrderBookCache:
    def __init__(self):
        self.quotes: Dict[tuple, Quote]={}
    def update(self, q: Quote):
        self.quotes[(q.venue,q.symbol)]=q
    def for_symbol(self,symbol):
        return [q for (_,s),q in self.quotes.items() if s==symbol]

class FastArbitrageEngine:
    def __init__(self, executor, size_usd=25.0, min_interval_ms=25):
        self.executor=executor; self.size_usd=size_usd
        self.min_interval_ms=min_interval_ms; self.cache=OrderBookCache()
        self.latency: Dict[str,LatencyStats]={}; self._last_exec=0.0
        self.running=False
    async def on_quote(self,q:Quote):
        t=time.perf_counter(); self.cache.update(q)
        ops=cross_venue_opportunities(self.cache.for_symbol(q.symbol),self.size_usd)
        if not ops: return None
        now=time.perf_counter()*1000
        if now-self._last_exec < self.min_interval_ms: return None
        self._last_exec=now
        result=await self.executor.execute(ops[0])
        elapsed=(time.perf_counter()-t)*1000
        self.latency.setdefault(q.venue,LatencyStats()).add(elapsed)
        return result

async def consume_stream(stream, engine:FastArbitrageEngine):
    engine.running=True
    async for quote in stream:
        if not engine.running: break
        await engine.on_quote(quote)
