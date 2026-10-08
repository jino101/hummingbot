"""Public CCXT L2 orderbooks -> conservative, depth-aware paper candidates.

Architecture inspired by CCXT's fetch_order_book API (MIT dependency).
No upstream source files copied. This module never creates orders.
"""
import math
import time
from dataclasses import dataclass
from typing import Mapping, Sequence

DEFAULT_EXCHANGES = ("binance","bybit","okx","kucoin","gateio","mexc",
                     "bitget","kraken","coinbase","bingx","bitmart","coinex","xt")


@dataclass(frozen=True)
class DepthBook:
    venue: str
    symbol: str
    bids: tuple
    asks: tuple
    observed_ms: int
    fee_pct: float = 0.1


def normalize_book(venue, symbol, raw, observed_ms=None, fee_pct=0.1):
    """Reject empty, non-finite, crossed or unpriced books."""
    if not isinstance(raw, Mapping):
        return None
    def levels(key, reverse):
        result = []
        for level in raw.get(key, []):
            try:
                price, amount = float(level[0]), float(level[1])
            except (ValueError, TypeError, IndexError, OverflowError):
                continue
            if math.isfinite(price) and math.isfinite(amount) and price > 0 and amount > 0:
                result.append((price, amount))
        return tuple(sorted(result, reverse=reverse))
    bids, asks = levels("bids", True), levels("asks", False)
    if not bids or not asks or bids[0][0] > asks[0][0]:
        return None
    fee = float(fee_pct)
    if not math.isfinite(fee) or fee < 0:
        return None
    return DepthBook(str(venue), str(symbol), bids, asks,
                     int(observed_ms if observed_ms is not None else time.time()*1000), fee)


def buy_base_with_usd(asks: Sequence[tuple], usd: float):
    """Calculate acquired base for a quote-currency budget; 0 if depth insufficient."""
    remaining = float(usd)
    acquired = 0.0
    if not math.isfinite(remaining) or remaining <= 0:
        return 0.0
    for price, qty in asks:
        spend = min(remaining, price * qty)
        acquired += spend / price
        remaining -= spend
        if remaining <= 1e-8:
            return acquired
    return 0.0


def sell_base_for_quote(bids: Sequence[tuple], base_qty: float):
    """Return quote proceeds or 0 when bid depth cannot fully fill the base quantity."""
    remaining = float(base_qty)
    proceeds = 0.0
    if not math.isfinite(remaining) or remaining <= 0:
        return 0.0
    for price, qty in bids:
        used = min(remaining, qty)
        proceeds += used * price
        remaining -= used
        if remaining <= 1e-10:
            return proceeds
    return 0.0


def scan_depth_books(books, size_usd=25.0, min_net_pct=0.35,
                     max_age_ms=5000, now_ms=None, extra_cost_pct=0.15):
    """Paper-only comparison. All orderbooks must use a USD-pegged quote asset.

    Fees are estimates. Cross-venue custody/transfer/settlement is NOT simulated.
    """
    now = int(time.time()*1000) if now_ms is None else int(now_ms)
    fresh = [b for b in books if 0 <= now-b.observed_ms <= max_age_ms]
    opportunities = []
    for buy in fresh:
        for sell in fresh:
            if buy.venue == sell.venue or buy.symbol != sell.symbol:
                continue
            amount = buy_base_with_usd(buy.asks, size_usd)
            if not amount:
                continue
            proceeds = sell_base_for_quote(sell.bids, amount)
            if not proceeds:
                continue
            gross_pct = (proceeds / size_usd - 1)*100
            net_pct = gross_pct - buy.fee_pct - sell.fee_pct - extra_cost_pct
            if net_pct >= min_net_pct:
                opportunities.append({"symbol":buy.symbol, "buy":buy.venue,
                    "sell":sell.venue, "size_usd":size_usd,
                    "base_qty":amount, "gross_pct":gross_pct,
                    "estimated_net_pct":net_pct,
                    "estimated_profit_usd":size_usd*net_pct/100})
    return sorted(opportunities, key=lambda x:x["estimated_net_pct"], reverse=True)


def fetch_public_books(exchanges=DEFAULT_EXCHANGES, symbols=("SOL/USDT","BTC/USDT"),
                       limit=20, fee_pct=0.1):
    """CCXT sync REST; public endpoints only. Never creates orders."""
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError("Install ccxt: python -m pip install ccxt") from exc
    books, errors = [], {}
    for name in exchanges:
        instance = None
        try:
            cls = getattr(ccxt, name)
            instance = cls({"enableRateLimit": True, "timeout": 10000})
            instance.load_markets()
            for symbol in symbols:
                if symbol not in instance.markets:
                    errors[f"{name}:{symbol}"] = "market_unavailable"
                    continue
                try:
                    raw = instance.fetch_order_book(symbol, limit)
                    book = normalize_book(name, symbol, raw, fee_pct=fee_pct)
                    if book is None:
                        errors[f"{name}:{symbol}"] = "invalid_orderbook"
                    else:
                        books.append(book)
                except Exception as exc:
                    errors[f"{name}:{symbol}"] = str(exc)
        except Exception as exc:
            errors[name] = str(exc)
        finally:
            if instance is not None and hasattr(instance, "close"):
                instance.close()
    return books, errors
