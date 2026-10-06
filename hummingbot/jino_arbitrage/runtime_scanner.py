from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
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



def scan_provider_pairs(
    market_data_provider,
    connector_names: Iterable[str],
    trading_pairs: Iterable[str],
    requested_amount_base: Decimal,
    policy: ScannerPolicy,
    taker_fees_pct: Optional[Dict[str, Decimal]] = None,
    networks: Optional[Dict[str, List[NetworkStatus]]] = None,
):
    """Scan multiple pairs and return one globally ranked opportunity list."""
    opportunities = []
    for trading_pair in trading_pairs:
        opportunities.extend(
            scan_provider_pair(
                market_data_provider=market_data_provider,
                connector_names=connector_names,
                trading_pair=trading_pair,
                requested_amount_base=requested_amount_base,
                policy=policy,
                taker_fees_pct=taker_fees_pct,
                networks=networks,
            )
        )
    return sorted(opportunities, key=lambda item: item.net_spread_pct, reverse=True)


def build_provider_quotes_for_quote_amount(
    market_data_provider,
    connector_names: Iterable[str],
    trading_pair: str,
    quote_amount: Decimal,
    networks: Optional[Dict[str, List[NetworkStatus]]] = None,
    observed_at: Optional[float] = None,
) -> List[VenueQuote]:
    """Build conservative, amount-aware scanner quotes without submitting orders.

    The order book is queried for the requested quote notional on each connector.
    Taker fee percentages are read from the connector fee model. Any connector
    whose depth/fee information cannot be read is skipped.
    """
    quote_amount = _d(quote_amount)
    if quote_amount <= 0:
        return []

    networks = networks or {}
    ts = observed_at if observed_at is not None else market_data_provider.time()
    quotes: List[VenueQuote] = []
    base, quote = trading_pair.split("-")

    for connector_name in connector_names:
        try:
            connector = market_data_provider.get_connector(connector_name)
            buy_depth = market_data_provider.get_price_for_quote_volume(
                connector_name, trading_pair, float(quote_amount), True
            )
            sell_depth = market_data_provider.get_price_for_quote_volume(
                connector_name, trading_pair, float(quote_amount), False
            )
            buy_price = _d(buy_depth.result_price)
            sell_price = _d(sell_depth.result_price)
            if buy_price <= 0 or sell_price <= 0:
                continue

            buy_base = quote_amount / buy_price
            sell_base = quote_amount / sell_price
            amount_base = min(buy_base, sell_base)
            if amount_base <= 0:
                continue

            buy_fee = connector.get_fee(
                base_currency=base,
                quote_currency=quote,
                order_type=OrderType.MARKET,
                order_side=TradeType.BUY,
                amount=amount_base,
                price=buy_price,
                is_maker=False,
            )
            sell_fee = connector.get_fee(
                base_currency=base,
                quote_currency=quote,
                order_type=OrderType.MARKET,
                order_side=TradeType.SELL,
                amount=amount_base,
                price=sell_price,
                is_maker=False,
            )
            taker_fee_pct = max(_d(getattr(buy_fee, "percent", 0)), _d(getattr(sell_fee, "percent", 0)))

            quotes.append(
                VenueQuote(
                    exchange=connector_name,
                    trading_pair=trading_pair,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    taker_fee_pct=taker_fee_pct,
                    max_buy_base=buy_base,
                    max_sell_base=sell_base,
                    networks=networks.get(connector_name, ()),
                    observed_at=ts,
                )
            )
        except Exception:
            continue

    return quotes


def scan_provider_pair_for_quote_amount(
    market_data_provider,
    connector_names: Iterable[str],
    trading_pair: str,
    quote_amount: Decimal,
    policy: ScannerPolicy,
    networks: Optional[Dict[str, List[NetworkStatus]]] = None,
):
    """Amount-aware, read-only scan for a hypothetical quote notional."""
    now = market_data_provider.time()
    quotes = build_provider_quotes_for_quote_amount(
        market_data_provider=market_data_provider,
        connector_names=connector_names,
        trading_pair=trading_pair,
        quote_amount=quote_amount,
        networks=networks,
        observed_at=now,
    )
    if not quotes:
        return []
    requested_amount_base = min(
        min(quote.max_buy_base, quote.max_sell_base)
        for quote in quotes
    )
    return scan_opportunities(
        quotes=quotes,
        requested_amount_base=requested_amount_base,
        policy=policy,
        now_timestamp=now,
    )
