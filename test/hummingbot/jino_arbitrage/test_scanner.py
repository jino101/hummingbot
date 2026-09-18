from decimal import Decimal

from hummingbot.jino_arbitrage.opportunity import NetworkStatus, VenueQuote
from hummingbot.jino_arbitrage.scanner import ScannerPolicy, common_trading_pairs, scan_opportunities


def q(exchange: str, pair: str, buy: str, sell: str, fee: str = "0", networks=()):
    return VenueQuote(
        exchange=exchange,
        trading_pair=pair,
        buy_price=Decimal(buy),
        sell_price=Decimal(sell),
        taker_fee_pct=Decimal(fee),
        max_buy_base=Decimal("1"),
        max_sell_base=Decimal("1"),
        networks=networks,
    )


def test_common_pairs_normalizes_and_filters():
    pairs = {
        "binance": ["btc-usdt", "ETH-USDT", "SOL-USDT"],
        "kucoin": ["BTC-USDT", "eth-usdt", "XRP-USDT"],
        "mexc": ["BTC-USDT", "ETH-USDT"],
    }
    assert common_trading_pairs(pairs) == ["BTC-USDT", "ETH-USDT"]
    assert common_trading_pairs(pairs, allow_pairs=["eth-usdt"]) == ["ETH-USDT"]
    assert common_trading_pairs(pairs, deny_pairs=["btc-usdt"]) == ["ETH-USDT"]


def test_scanner_policy_allow_deny_and_min_profit():
    quotes = [
        q("a", "BTC-USDT", "100", "99", "0.001"),
        q("b", "BTC-USDT", "102", "103", "0.001"),
        q("a", "ETH-USDT", "50", "49.8", "0.001"),
        q("b", "ETH-USDT", "50.1", "50.2", "0.001"),
    ]

    policy = ScannerPolicy(
        min_net_spread_pct=Decimal("0.005"),
        allow_pairs=["BTC-USDT", "ETH-USDT"],
        deny_pairs=["ETH-USDT"],
    )
    out = scan_opportunities(quotes, Decimal("0.1"), policy)
    assert out
    assert all(item.trading_pair == "BTC-USDT" for item in out)
    assert out[0].buy_exchange == "a"
    assert out[0].sell_exchange == "b"


def test_scanner_can_require_rebalance_transferability():
    buy = q(
        "a",
        "BTC-USDT",
        "100",
        "99",
        networks=[NetworkStatus("ERC20", deposit_enabled=True, withdrawal_enabled=False)],
    )
    sell_ok = q(
        "b",
        "BTC-USDT",
        "102",
        "103",
        networks=[NetworkStatus("Ethereum", deposit_enabled=False, withdrawal_enabled=True)],
    )
    sell_unknown = q(
        "c",
        "BTC-USDT",
        "102",
        "104",
        networks=[NetworkStatus("TRC20", deposit_enabled=None, withdrawal_enabled=None)],
    )

    out = scan_opportunities(
        [buy, sell_ok, sell_unknown],
        Decimal("0.1"),
        ScannerPolicy(require_rebalance_transferable=True),
    )
    assert out
    assert all(item.rebalance_transferable for item in out)
    assert any(item.sell_exchange == "b" for item in out)
    assert all(item.sell_exchange != "c" for item in out)
