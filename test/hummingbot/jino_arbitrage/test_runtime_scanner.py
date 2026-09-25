from decimal import Decimal
from unittest.mock import MagicMock

from hummingbot.core.data_type.common import PriceType
from hummingbot.jino_arbitrage.runtime_scanner import (
    build_provider_quotes,
    build_provider_quotes_for_quote_amount,
    scan_provider_pair,
    scan_provider_pair_for_quote_amount,
    scan_provider_pairs,
)
from hummingbot.jino_arbitrage.scanner import ScannerPolicy


def provider_with_prices():
    provider = MagicMock()
    provider.time.return_value = 1000.0

    def price(connector, pair, price_type):
        data = {
            ("binance_paper_trade", PriceType.BestAsk): Decimal("100"),
            ("binance_paper_trade", PriceType.BestBid): Decimal("99.8"),
            ("kucoin_paper_trade", PriceType.BestAsk): Decimal("102"),
            ("kucoin_paper_trade", PriceType.BestBid): Decimal("103"),
        }
        return data[(connector, price_type)]

    provider.get_price_by_type.side_effect = price
    return provider


def test_build_provider_quotes_reads_best_bid_and_ask():
    provider = provider_with_prices()
    quotes = build_provider_quotes(
        provider,
        ["binance_paper_trade", "kucoin_paper_trade"],
        "BTC-USDT",
        Decimal("0.1"),
        taker_fees_pct={
            "binance_paper_trade": Decimal("0.001"),
            "kucoin_paper_trade": Decimal("0.001"),
        },
    )
    assert len(quotes) == 2
    assert quotes[0].buy_price == Decimal("100")
    assert quotes[0].sell_price == Decimal("99.8")
    assert all(q.observed_at == 1000.0 for q in quotes)


def test_runtime_scanner_ranks_cross_exchange_opportunity():
    provider = provider_with_prices()
    opportunities = scan_provider_pair(
        provider,
        ["binance_paper_trade", "kucoin_paper_trade"],
        "BTC-USDT",
        Decimal("0.1"),
        ScannerPolicy(
            min_net_spread_pct=Decimal("0.005"),
            max_quote_age_seconds=5,
        ),
        taker_fees_pct={
            "binance_paper_trade": Decimal("0.001"),
            "kucoin_paper_trade": Decimal("0.001"),
        },
    )
    assert opportunities
    best = opportunities[0]
    assert best.buy_exchange == "binance_paper_trade"
    assert best.sell_exchange == "kucoin_paper_trade"


def test_runtime_scanner_skips_unavailable_connector():
    provider = provider_with_prices()
    quotes = build_provider_quotes(
        provider,
        ["binance_paper_trade", "missing"],
        "BTC-USDT",
        Decimal("0.1"),
    )
    assert len(quotes) == 1
    assert quotes[0].exchange == "binance_paper_trade"



def test_runtime_scanner_can_rank_multiple_pairs():
    provider = provider_with_prices()

    original = provider.get_price_by_type.side_effect
    def price(connector, pair, price_type):
        if pair == "ETH-USDT":
            data = {
                ("binance_paper_trade", PriceType.BestAsk): Decimal("50"),
                ("binance_paper_trade", PriceType.BestBid): Decimal("49.9"),
                ("kucoin_paper_trade", PriceType.BestAsk): Decimal("50.2"),
                ("kucoin_paper_trade", PriceType.BestBid): Decimal("50.3"),
            }
            return data[(connector, price_type)]
        return original(connector, pair, price_type)

    provider.get_price_by_type.side_effect = price

    opportunities = scan_provider_pairs(
        provider,
        ["binance_paper_trade", "kucoin_paper_trade"],
        ["BTC-USDT", "ETH-USDT"],
        Decimal("0.1"),
        ScannerPolicy(min_net_spread_pct=Decimal("0.001")),
    )
    assert opportunities
    assert {item.trading_pair for item in opportunities} == {"BTC-USDT", "ETH-USDT"}
    assert opportunities[0].net_spread_pct >= opportunities[-1].net_spread_pct


def test_amount_aware_read_only_scanner_uses_depth_and_fees():
    provider = MagicMock()
    provider.time.return_value = 1000.0

    def depth(connector, pair, quote_volume, is_buy):
        result = MagicMock()
        prices = {
            ("binance", True): Decimal("100"),
            ("binance", False): Decimal("99.8"),
            ("kucoin", True): Decimal("102"),
            ("kucoin", False): Decimal("103"),
        }
        result.result_price = prices[(connector, is_buy)]
        return result

    provider.get_price_for_quote_volume.side_effect = depth

    connectors = {}
    for name in ("binance", "kucoin"):
        connector = MagicMock()
        fee = MagicMock()
        fee.percent = Decimal("0.001")
        connector.get_fee.return_value = fee
        connectors[name] = connector
    provider.get_connector.side_effect = lambda name: connectors[name]

    quotes = build_provider_quotes_for_quote_amount(
        provider,
        ["binance", "kucoin"],
        "BTC-USDT",
        Decimal("25"),
    )
    assert len(quotes) == 2
    assert quotes[0].buy_price == Decimal("100")
    assert quotes[1].sell_price == Decimal("103")
    assert all(q.taker_fee_pct == Decimal("0.001") for q in quotes)

    opportunities = scan_provider_pair_for_quote_amount(
        provider,
        ["binance", "kucoin"],
        "BTC-USDT",
        Decimal("25"),
        ScannerPolicy(
            min_net_spread_pct=Decimal("0"),
            estimated_slippage_pct=Decimal("0.001"),
            max_quote_age_seconds=5,
        ),
    )
    assert opportunities
    assert opportunities[0].buy_exchange == "binance"
    assert opportunities[0].sell_exchange == "kucoin"


def test_amount_aware_read_only_scanner_skips_bad_connector():
    provider = MagicMock()
    provider.time.return_value = 1000.0
    provider.get_price_for_quote_volume.side_effect = RuntimeError("depth unavailable")

    quotes = build_provider_quotes_for_quote_amount(
        provider,
        ["binance"],
        "BTC-USDT",
        Decimal("25"),
    )
    assert quotes == []
