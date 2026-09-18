from decimal import Decimal

from hummingbot.jino_arbitrage.opportunity import (
    NetworkStatus,
    VenueQuote,
    calculate_opportunity,
    find_best_opportunities,
)


def quote(exchange: str, buy: str, sell: str, fee: str, networks=()):
    return VenueQuote(
        exchange=exchange,
        trading_pair="BTC-USDT",
        buy_price=Decimal(buy),
        sell_price=Decimal(sell),
        taker_fee_pct=Decimal(fee),
        max_buy_base=Decimal("1"),
        max_sell_base=Decimal("1"),
        networks=networks,
    )


def test_calculates_net_spread_after_fees_and_slippage():
    buy_venue = quote("a", "100", "99", "0.001")
    sell_venue = quote("b", "102", "103", "0.002")
    opportunity = calculate_opportunity(
        buy_venue,
        sell_venue,
        requested_amount_base=Decimal("0.5"),
        estimated_slippage_pct=Decimal("0.001"),
    )
    assert opportunity is not None
    assert opportunity.gross_spread_pct == Decimal("0.03")
    assert opportunity.estimated_fee_pct == Decimal("0.003")
    assert opportunity.net_spread_pct == Decimal("0.026")
    assert opportunity.expected_profit_quote == Decimal("1.3000")


def test_caps_amount_by_available_depth():
    buy_venue = VenueQuote(
        exchange="a",
        trading_pair="BTC-USDT",
        buy_price=Decimal("100"),
        sell_price=Decimal("99"),
        taker_fee_pct=Decimal("0"),
        max_buy_base=Decimal("0.2"),
        max_sell_base=Decimal("1"),
    )
    sell_venue = VenueQuote(
        exchange="b",
        trading_pair="BTC-USDT",
        buy_price=Decimal("102"),
        sell_price=Decimal("103"),
        taker_fee_pct=Decimal("0"),
        max_buy_base=Decimal("1"),
        max_sell_base=Decimal("0.1"),
    )
    opportunity = calculate_opportunity(buy_venue, sell_venue, Decimal("0.5"))
    assert opportunity is not None
    assert opportunity.amount_base == Decimal("0.1")


def test_network_aliases_match_and_unknown_fails_closed():
    buy_venue = quote(
        "a",
        "100",
        "99",
        "0",
        networks=[NetworkStatus("ERC20", deposit_enabled=True, withdrawal_enabled=None)],
    )
    sell_venue = quote(
        "b",
        "102",
        "103",
        "0",
        networks=[NetworkStatus("Ethereum", deposit_enabled=None, withdrawal_enabled=True)],
    )
    opportunity = calculate_opportunity(buy_venue, sell_venue, Decimal("0.1"))
    assert opportunity is not None
    assert opportunity.common_transfer_networks == ["ETHEREUM"]
    assert opportunity.rebalance_transferable is True

    unknown_buy = quote(
        "c",
        "100",
        "99",
        "0",
        networks=[NetworkStatus("ERC20", deposit_enabled=None, withdrawal_enabled=None)],
    )
    unknown = calculate_opportunity(unknown_buy, sell_venue, Decimal("0.1"))
    assert unknown is not None
    assert unknown.rebalance_transferable is False


def test_finds_and_sorts_only_profitable_opportunities():
    quotes = [
        quote("a", "100", "99", "0.001"),
        quote("b", "102", "103", "0.001"),
        quote("c", "101", "101.5", "0.001"),
    ]
    opportunities = find_best_opportunities(
        quotes,
        requested_amount_base=Decimal("0.1"),
        min_net_spread_pct=Decimal("0.005"),
    )
    assert opportunities
    assert opportunities[0].buy_exchange == "a"
    assert opportunities[0].sell_exchange == "b"
    assert all(item.net_spread_pct >= Decimal("0.005") for item in opportunities)



def test_rebalance_fee_uses_cheapest_common_enabled_network():
    buy_venue = quote(
        "a",
        "100",
        "99",
        "0",
        networks=[
            NetworkStatus("ERC20", deposit_enabled=True, withdrawal_enabled=False),
            NetworkStatus("TRC20", deposit_enabled=True, withdrawal_enabled=False),
        ],
    )
    sell_venue = quote(
        "b",
        "102",
        "103",
        "0",
        networks=[
            NetworkStatus("Ethereum", deposit_enabled=False, withdrawal_enabled=True, withdrawal_fee_quote=Decimal("3")),
            NetworkStatus("Tron", deposit_enabled=False, withdrawal_enabled=True, withdrawal_fee_quote=Decimal("1")),
        ],
    )
    opportunity = calculate_opportunity(buy_venue, sell_venue, Decimal("0.5"))
    assert opportunity is not None
    assert opportunity.common_transfer_networks == ["ETHEREUM", "TRON"]
    assert opportunity.estimated_rebalance_fee_quote == Decimal("1")
    assert opportunity.expected_profit_after_rebalance_quote == opportunity.expected_profit_quote - Decimal("1")
