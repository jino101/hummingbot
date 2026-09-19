from decimal import Decimal
from unittest.mock import MagicMock

from hummingbot.core.data_type.common import PriceType
from hummingbot.jino_arbitrage.runtime_scanner import build_provider_quotes, scan_provider_pair
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
