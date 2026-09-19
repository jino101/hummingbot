from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from hummingbot.core.data_type.common import PriceType
from hummingbot.jino_arbitrage.opportunity import NetworkStatus, VenueQuote
from hummingbot.jino_arbitrage.scanner import ScannerPolicy, scan_opportunities


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def build_provider_quotes(
    market_data_provider,
    connector_names: Iterable[str],
    trading_pair: str,
    requested_amount_base: Decimal,
    taker_fees_pct: Optional[Dict[str, Decimal]] = None,
    networks: Optional[Dict[str, List[NetworkStatus]]] = None,
    observed_at: Optional[float] = None,
) -> List[VenueQuote]:
    """Create scanner quotes from Hummingbot's current best bid/ask data.

    This is scanner-only glue. It never submits orders or accesses secrets directly.
    Connectors that do not currently expose valid bid/ask data are skipped.
    """
    requested_amount_base = _d(requested_amount_base)
    if requested_amount_base <= 0:
        return []

    taker_fees_pct = taker_fees_pct or {}
    networks = networks or {}
    ts = observed_at if observed_at is not None else market_data_provider.time()
    quotes: List[VenueQuote] = []

    for connector in connector_names:
        try:
            ask = market_data_provider.get_price_by_type(connector, trading_pair, PriceType.BestAsk)
            bid = market_data_provider.get_price_by_type(connector, trading_pair, PriceType.BestBid)
            ask = _d(ask)
            bid = _d(bid)
            if ask <= 0 or bid <= 0:
                continue

            # The actual executor performs amount-aware quote requests before execution.
            # For scanner ranking we conservatively cap the quoted depth to the requested amount.
            quotes.append(
                VenueQuote(
                    exchange=connector,
                    trading_pair=trading_pair,
                    buy_price=ask,
                    sell_price=bid,
                    taker_fee_pct=_d(taker_fees_pct.get(connector, Decimal("0"))),
                    max_buy_base=requested_amount_base,
                    max_sell_base=requested_amount_base,
                    networks=networks.get(connector, ()),
                    observed_at=ts,
                )
            )
        except Exception:
            # A temporarily unavailable connector must not poison the whole scanner.
            continue

    return quotes


def scan_provider_pair(
    market_data_provider,
    connector_names: Iterable[str],
    trading_pair: str,
    requested_amount_base: Decimal,
    policy: ScannerPolicy,
    taker_fees_pct: Optional[Dict[str, Decimal]] = None,
    networks: Optional[Dict[str, List[NetworkStatus]]] = None,
):
    """Scan one pair across live Hummingbot market-data providers without trading."""
    now = market_data_provider.time()
    quotes = build_provider_quotes(
        market_data_provider=market_data_provider,
        connector_names=connector_names,
        trading_pair=trading_pair,
        requested_amount_base=requested_amount_base,
        taker_fees_pct=taker_fees_pct,
        networks=networks,
        observed_at=now,
    )
    return scan_opportunities(
        quotes=quotes,
        requested_amount_base=requested_amount_base,
        policy=policy,
        now_timestamp=now,
    )
