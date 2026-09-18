from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Set


@dataclass(frozen=True)
class NetworkStatus:
    network: str
    deposit_enabled: Optional[bool]
    withdrawal_enabled: Optional[bool]
    withdrawal_fee_quote: Decimal = Decimal("0")


@dataclass(frozen=True)
class VenueQuote:
    exchange: str
    trading_pair: str
    buy_price: Decimal
    sell_price: Decimal
    taker_fee_pct: Decimal
    max_buy_base: Decimal
    max_sell_base: Decimal
    networks: Sequence[NetworkStatus] = ()


@dataclass(frozen=True)
class ArbitrageOpportunity:
    trading_pair: str
    buy_exchange: str
    sell_exchange: str
    amount_base: Decimal
    buy_price: Decimal
    sell_price: Decimal
    gross_spread_pct: Decimal
    estimated_fee_pct: Decimal
    estimated_slippage_pct: Decimal
    net_spread_pct: Decimal
    expected_profit_quote: Decimal
    common_transfer_networks: Sequence[str]
    rebalance_transferable: bool
    estimated_rebalance_fee_quote: Decimal
    expected_profit_after_rebalance_quote: Decimal


def _canonical_network(name: str) -> str:
    normalized = name.strip().upper().replace(" ", "").replace("_", "").replace("-", "")
    aliases = {
        "ERC20": "ETHEREUM",
        "ETH": "ETHEREUM",
        "ETHEREUM": "ETHEREUM",
        "TRC20": "TRON",
        "TRX": "TRON",
        "TRON": "TRON",
        "BEP20": "BSC",
        "BSC": "BSC",
        "BNBSMARTCHAIN": "BSC",
        "ARBITRUMONE": "ARBITRUM",
        "ARBITRUM": "ARBITRUM",
        "OPTIMISM": "OPTIMISM",
        "POLYGON": "POLYGON",
        "MATIC": "POLYGON",
        "SOL": "SOLANA",
        "SOLANA": "SOLANA",
    }
    return aliases.get(normalized, normalized)


def _withdrawable_networks(networks: Sequence[NetworkStatus]) -> Set[str]:
    return {
        _canonical_network(network.network)
        for network in networks
        if network.withdrawal_enabled is True
    }


def _depositable_networks(networks: Sequence[NetworkStatus]) -> Set[str]:
    return {
        _canonical_network(network.network)
        for network in networks
        if network.deposit_enabled is True
    }


def common_transfer_networks(buy_venue: VenueQuote, sell_venue: VenueQuote) -> List[str]:
    """Networks that can move the asset from the sell venue back to the buy venue.

    This models the common rebalance direction after buying base on the buy venue and
    selling base on the sell venue. Unknown status fails closed because only explicit
    True values are considered usable.
    """
    usable = _withdrawable_networks(sell_venue.networks) & _depositable_networks(buy_venue.networks)
    return sorted(usable)


def estimated_rebalance_fee_quote(buy_venue: VenueQuote, sell_venue: VenueQuote) -> Decimal:
    """Cheapest explicitly usable withdrawal fee for the modeled rebalance direction."""
    common = set(common_transfer_networks(buy_venue, sell_venue))
    fees = [
        network.withdrawal_fee_quote
        for network in sell_venue.networks
        if _canonical_network(network.network) in common
        and network.withdrawal_enabled is True
        and network.withdrawal_fee_quote >= 0
    ]
    return min(fees) if fees else Decimal("0")


def calculate_opportunity(
    buy_venue: VenueQuote,
    sell_venue: VenueQuote,
    requested_amount_base: Decimal,
    estimated_slippage_pct: Decimal = Decimal("0"),
) -> Optional[ArbitrageOpportunity]:
    if buy_venue.trading_pair != sell_venue.trading_pair:
        return None
    if requested_amount_base <= 0:
        return None
    if buy_venue.buy_price <= 0 or sell_venue.sell_price <= 0:
        return None

    amount_base = min(requested_amount_base, buy_venue.max_buy_base, sell_venue.max_sell_base)
    if amount_base <= 0:
        return None

    gross_spread_pct = (sell_venue.sell_price - buy_venue.buy_price) / buy_venue.buy_price
    estimated_fee_pct = buy_venue.taker_fee_pct + sell_venue.taker_fee_pct
    net_spread_pct = gross_spread_pct - estimated_fee_pct - estimated_slippage_pct
    buy_notional = amount_base * buy_venue.buy_price
    expected_profit_quote = buy_notional * net_spread_pct
    networks = common_transfer_networks(buy_venue, sell_venue)
    rebalance_fee_quote = estimated_rebalance_fee_quote(buy_venue, sell_venue)
    expected_after_rebalance = expected_profit_quote - rebalance_fee_quote

    return ArbitrageOpportunity(
        trading_pair=buy_venue.trading_pair,
        buy_exchange=buy_venue.exchange,
        sell_exchange=sell_venue.exchange,
        amount_base=amount_base,
        buy_price=buy_venue.buy_price,
        sell_price=sell_venue.sell_price,
        gross_spread_pct=gross_spread_pct,
        estimated_fee_pct=estimated_fee_pct,
        estimated_slippage_pct=estimated_slippage_pct,
        net_spread_pct=net_spread_pct,
        expected_profit_quote=expected_profit_quote,
        common_transfer_networks=networks,
        rebalance_transferable=len(networks) > 0,
        estimated_rebalance_fee_quote=rebalance_fee_quote,
        expected_profit_after_rebalance_quote=expected_after_rebalance,
    )


def find_best_opportunities(
    quotes: Iterable[VenueQuote],
    requested_amount_base: Decimal,
    min_net_spread_pct: Decimal = Decimal("0"),
    estimated_slippage_pct: Decimal = Decimal("0"),
) -> List[ArbitrageOpportunity]:
    quote_list = list(quotes)
    opportunities: List[ArbitrageOpportunity] = []

    for buy_venue in quote_list:
        for sell_venue in quote_list:
            if buy_venue.exchange == sell_venue.exchange:
                continue
            opportunity = calculate_opportunity(
                buy_venue=buy_venue,
                sell_venue=sell_venue,
                requested_amount_base=requested_amount_base,
                estimated_slippage_pct=estimated_slippage_pct,
            )
            if opportunity is not None and opportunity.net_spread_pct >= min_net_spread_pct:
                opportunities.append(opportunity)

    return sorted(opportunities, key=lambda item: item.net_spread_pct, reverse=True)
