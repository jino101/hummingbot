from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from hummingbot.jino_arbitrage.live_checks import (
    ApiPermissionSnapshot,
    BalanceSnapshot,
    NetworkSnapshot,
    assess_live_readiness,
    build_common_transfer_estimates,
    collect_live_readiness,
    estimate_network_transfer_minutes,
    parse_binance_network_statuses,
    parse_binance_permissions,
    parse_kucoin_network_statuses,
    parse_kucoin_permissions,
)


def test_binance_network_parser_is_chain_specific_and_converts_fee_to_quote():
    payload = [
        {
            "coin": "BTC",
            "networkList": [
                {
                    "network": "BTC",
                    "depositEnable": True,
                    "withdrawEnable": True,
                    "withdrawFee": "0.0001",
                },
                {
                    "network": "BSC",
                    "depositEnable": True,
                    "withdrawEnable": False,
                    "withdrawFee": "0.00001",
                },
            ],
        }
    ]
    statuses = parse_binance_network_statuses(payload, "BTC", Decimal("100000"))
    assert len(statuses) == 2
    assert statuses[0].network == "BTC"
    assert statuses[0].withdrawal_fee_quote == Decimal("10")
    assert statuses[1].withdrawal_enabled is False


def test_kucoin_network_parser_supports_v3_currency_shape():
    payload = {
        "code": "200000",
        "data": {
            "currency": "BTC",
            "chains": [
                {
                    "chainName": "BTC",
                    "withdrawalMinFee": "0.00009",
                    "isWithdrawEnabled": True,
                    "isDepositEnabled": True,
                }
            ],
        },
    }
    statuses = parse_kucoin_network_statuses(payload, "BTC", Decimal("100000"))
    assert len(statuses) == 1
    assert statuses[0].withdrawal_fee_quote == Decimal("9")
    assert statuses[0].deposit_enabled is True


def test_permission_parsers_require_trading_and_detect_withdrawal_rights():
    binance = parse_binance_permissions(
        {
            "enableReading": True,
            "enableSpotAndMarginTrading": True,
            "enableWithdrawals": False,
        },
        observed_at=100,
    )
    assert binance.can_read and binance.can_spot_trade and not binance.can_withdraw

    kucoin = parse_kucoin_permissions(
        {"data": {"permission": "General,Spot,Withdrawal"}},
        observed_at=100,
    )
    assert kucoin.can_read and kucoin.can_spot_trade and kucoin.can_withdraw


def _healthy_report_inputs():
    now = 1000.0
    network = (
        __import__("hummingbot.jino_arbitrage.opportunity", fromlist=["NetworkStatus"]).NetworkStatus(
            "BTC", True, True, Decimal("5")
        ),
    )
    permissions = {
        "binance": ApiPermissionSnapshot("binance", now, True, True, False),
        "kucoin": ApiPermissionSnapshot("kucoin", now, True, True, False),
    }
    networks = {
        "binance": NetworkSnapshot("binance", "BTC", now, network),
        "kucoin": NetworkSnapshot("kucoin", "BTC", now, network),
    }
    balances = {
        "binance": BalanceSnapshot("binance", Decimal("0.001"), Decimal("100")),
        "kucoin": BalanceSnapshot("kucoin", Decimal("0.001"), Decimal("100")),
    }
    return now, permissions, networks, balances


def test_live_readiness_passes_only_when_permissions_networks_and_balances_are_safe():
    now, permissions, networks, balances = _healthy_report_inputs()
    report = assess_live_readiness(
        connector_names=["binance", "kucoin"],
        trading_pair="BTC-USDT",
        total_amount_quote=Decimal("25"),
        asset_quote_price=Decimal("100000"),
        connector_ready={"binance": True, "kucoin": True},
        permissions=permissions,
        network_snapshots=networks,
        balances=balances,
        now=now,
    )
    assert report.ready is True
    assert report.common_rebalance_networks == ("BITCOIN",)


def test_live_readiness_fails_closed_on_withdrawal_permission_and_stale_networks():
    now, permissions, networks, balances = _healthy_report_inputs()
    permissions["binance"] = ApiPermissionSnapshot("binance", now, True, True, True)
    networks["kucoin"] = NetworkSnapshot("kucoin", "BTC", now - 1000, networks["kucoin"].networks)

    report = assess_live_readiness(
        connector_names=["binance", "kucoin"],
        trading_pair="BTC-USDT",
        total_amount_quote=Decimal("25"),
        asset_quote_price=Decimal("100000"),
        connector_ready={"binance": True, "kucoin": True},
        permissions=permissions,
        network_snapshots=networks,
        balances=balances,
        now=now,
        max_age_seconds=120,
    )
    assert report.ready is False
    assert any("withdrawal permission" in reason for reason in report.reasons)
    assert any("stale" in reason for reason in report.reasons)


@pytest.mark.asyncio
async def test_collect_live_readiness_uses_live_connectors_and_fails_closed_on_probe_errors():
    provider = MagicMock()
    provider.time.return_value = 1000.0
    provider.get_rate.return_value = Decimal("100000")

    binance = MagicMock()
    binance.ready = True
    binance.domain = "com"
    binance.get_available_balance.side_effect = lambda asset: Decimal("1") if asset == "BTC" else Decimal("1000")
    binance._api_get = AsyncMock(side_effect=[
        {
            "enableReading": True,
            "enableSpotAndMarginTrading": True,
            "enableWithdrawals": False,
        },
        [
            {
                "coin": "BTC",
                "networkList": [
                    {
                        "network": "BTC",
                        "depositEnable": True,
                        "withdrawEnable": True,
                        "withdrawFee": "0.0001",
                    }
                ],
            }
        ],
    ])

    kucoin = MagicMock()
    kucoin.ready = True
    kucoin.get_available_balance.side_effect = lambda asset: Decimal("1") if asset == "BTC" else Decimal("1000")
    kucoin._api_get = AsyncMock(side_effect=[
        {"code": "200000", "data": {"permission": "General,Spot"}},
        {
            "code": "200000",
            "data": {
                "currency": "BTC",
                "chains": [
                    {
                        "chainName": "BTC",
                        "withdrawalMinFee": "0.0001",
                        "isWithdrawEnabled": True,
                        "isDepositEnabled": True,
                    }
                ],
            },
        },
    ])
    provider.get_connector.side_effect = lambda name: {"binance": binance, "kucoin": kucoin}[name]

    report = await collect_live_readiness(
        provider,
        ["binance", "kucoin"],
        "BTC-USDT",
        Decimal("25"),
        "USDT",
    )
    assert report.ready is True


def test_unknown_permissions_fail_closed():
    now, permissions, networks, balances = _healthy_report_inputs()
    permissions["kucoin"] = parse_kucoin_permissions({"data": {}}, observed_at=now)

    report = assess_live_readiness(
        connector_names=["binance", "kucoin"],
        trading_pair="BTC-USDT",
        total_amount_quote=Decimal("25"),
        asset_quote_price=Decimal("100000"),
        connector_ready={"binance": True, "kucoin": True},
        permissions=permissions,
        network_snapshots=networks,
        balances=balances,
        now=now,
    )

    assert report.ready is False
    assert any("withdrawal permission could not be verified" in reason for reason in report.reasons)


def test_transfer_eta_prefers_exchange_estimate():
    network = __import__("hummingbot.jino_arbitrage.opportunity", fromlist=["NetworkStatus"]).NetworkStatus(
        "BTC",
        True,
        True,
        Decimal("5"),
        min_confirmations=2,
        estimated_arrival_minutes=Decimal("7"),
    )
    estimate = estimate_network_transfer_minutes(network)
    assert estimate.estimated_minutes == Decimal("7")
    assert estimate.source == "exchange_estimate"


def test_transfer_eta_falls_back_to_confirmation_estimate():
    network = __import__("hummingbot.jino_arbitrage.opportunity", fromlist=["NetworkStatus"]).NetworkStatus(
        "BTC",
        True,
        True,
        Decimal("5"),
        min_confirmations=2,
    )
    estimate = estimate_network_transfer_minutes(network)
    assert estimate.estimated_minutes == Decimal("20")
    assert estimate.source == "confirmation_estimate"


def test_common_transfer_eta_uses_slower_exchange_estimate():
    NetworkStatus = __import__("hummingbot.jino_arbitrage.opportunity", fromlist=["NetworkStatus"]).NetworkStatus
    snapshots = [
        NetworkSnapshot(
            "binance",
            "BTC",
            1000,
            (NetworkStatus("BTC", True, True, Decimal("5"), estimated_arrival_minutes=Decimal("4")),),
        ),
        NetworkSnapshot(
            "kucoin",
            "BTC",
            1000,
            (NetworkStatus("Bitcoin", True, True, Decimal("6"), estimated_arrival_minutes=Decimal("9")),),
        ),
    ]
    estimates = build_common_transfer_estimates(snapshots)
    assert estimates[0].network == "BITCOIN"
    assert estimates[0].estimated_minutes == Decimal("9")
