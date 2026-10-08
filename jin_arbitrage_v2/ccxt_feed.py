"""Read-only CCXT REST quotes for rapid multi-exchange scanning.

Dependency: ccxt (MIT, https://github.com/ccxt/ccxt).
No API keys, wallets, order methods, or live execution.
"""
import asyncio
import time
from typing import Iterable

from .models import Quote, VenueType


def normalize_ccxt_ticker(venue, symbol, ticker, fee_pct=0.1):
    """Return top-of-book quote or None for invalid/incomplete tickers."""
    if not isinstance(ticker, dict):
        return None
    try:
        bid = float(ticker.get("bid") or 0)
        ask = float(ticker.get("ask") or 0)
        bid_size = float(ticker.get("bidVolume") or 0)
        ask_size = float(ticker.get("askVolume") or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    import math
    if not all(map(math.isfinite, (bid, ask, bid_size, ask_size))):
        return None
    if bid <= 0 or ask <= 0 or bid > ask or bid_size < 0 or ask_size < 0:
        return None
    timestamp_ms = ticker.get("timestamp")
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    try:
        timestamp_ms = int(timestamp_ms)
    except (ValueError, TypeError, OverflowError):
        return None
    return Quote(venue=venue, venue_type=VenueType.CEX,
                 symbol=symbol, bid=bid, ask=ask,
                 bid_size=bid_size, ask_size=ask_size,
                 fee_pct=float(fee_pct), timestamp_ms=timestamp_ms)


def fetch_public_quotes(venues: Iterable[str], symbols: Iterable[str], fee_pct=0.1):
    """Query public REST markets; return (quotes, errors), never place orders.

    This is a pollable fallback, NOT a replacement for WebSocket streaming.
    Fee is a configurable estimate, not a verified per-account fee.
    """
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError("Install CCXT: pip install ccxt") from exc

    out, errors = [], {}
    for venue in venues:
        exchange = None
        try:
            cls = getattr(ccxt, venue)
            exchange = cls({"enableRateLimit": True, "timeout": 10000})
            exchange.load_markets()
            for symbol in symbols:
                if symbol not in exchange.markets:
                    errors[f"{venue}:{symbol}"] = "market_unavailable"
                    continue
                try:
                    ticker = exchange.fetch_ticker(symbol)
                    quote = normalize_ccxt_ticker(venue, symbol, ticker, fee_pct)
                    if quote is None:
                        errors[f"{venue}:{symbol}"] = "invalid_or_incomplete_quote"
                    else:
                        out.append(quote)
                except Exception as exc:
                    errors[f"{venue}:{symbol}"] = str(exc)
        except Exception as exc:
            errors[venue] = str(exc)
        finally:
            if exchange is not None and hasattr(exchange, "close"):
                exchange.close()
    return out, errors


async def fetch_public_quotes_async(venues, symbols, fee_pct=0.1):
    return await asyncio.to_thread(fetch_public_quotes, venues, symbols, fee_pct)
