import asyncio
import random
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional

from .models import Quote

@dataclass
class FeedHealth:
    venue: str
    connected: bool = False
    reconnects: int = 0
    last_quote_ms: int = 0
    last_error: str = ""

    def is_stale(self, now_ms: Optional[int] = None, max_age_ms: int = 5000) -> bool:
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        return not self.last_quote_ms or now - self.last_quote_ms > max_age_ms

class ResilientStream:
    """Reconnect wrapper for read-only quote streams.

    The factory must return a fresh async iterable. No order/execution methods are used.
    """
    def __init__(self, venue: str, factory: Callable[[], object],
                 base_delay: float = 0.5, max_delay: float = 20.0,
                 max_reconnects: Optional[int] = None):
        self.venue = venue
        self.factory = factory
        self.base_delay = max(0.0, float(base_delay))
        self.max_delay = max(self.base_delay, float(max_delay))
        self.max_reconnects = max_reconnects
        self.health = FeedHealth(venue)

    async def __aiter__(self) -> AsyncIterator[Quote]:
        attempt = 0
        while self.max_reconnects is None or attempt <= self.max_reconnects:
            try:
                self.health.connected = True
                async for quote in self.factory():
                    self.health.last_quote_ms = int(quote.timestamp_ms or time.time() * 1000)
                    self.health.last_error = ""
                    attempt = 0
                    yield quote
                raise RuntimeError("stream_ended")
            except asyncio.CancelledError:
                self.health.connected = False
                raise
            except Exception as exc:
                self.health.connected = False
                self.health.last_error = f"{type(exc).__name__}: {exc}"
                attempt += 1
                self.health.reconnects += 1
                if self.max_reconnects is not None and attempt > self.max_reconnects:
                    raise RuntimeError(f"{self.venue}_reconnect_limit") from exc
                delay = min(self.max_delay, self.base_delay * (2 ** max(0, attempt - 1)))
                # Small jitter prevents synchronized reconnect storms.
                delay *= 0.9 + random.random() * 0.2
                await asyncio.sleep(delay)

def fresh_quote(quote: Quote, now_ms: Optional[int] = None, max_age_ms: int = 5000) -> bool:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    ts = int(quote.timestamp_ms or 0)
    return ts > 0 and 0 <= now - ts <= max_age_ms
