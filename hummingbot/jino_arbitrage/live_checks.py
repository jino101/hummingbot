import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from hummingbot.jino_arbitrage.opportunity import NetworkStatus


BINANCE_ALL_COINS_PATH = "/sapi/v1/capital/config/getall"
BINANCE_API_RESTRICTIONS_PATH = "/sapi/v1/account/apiRestrictions"
KUCOIN_CURRENCY_PATH_TEMPLATE = "/api/v3/currencies/{asset}"
KUCOIN_API_KEY_INFO_PATH = "/api/v1/user/api-key"


def _d(value, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _canonical_network(name: str) -> str:
    normalized = str(name or "").strip().upper().replace(" ", "").replace("_", "").replace("-", "")
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
        "BTC": "BITCOIN",
        "BITCOIN": "BITCOIN",
    }
    return aliases.get(normalized, normalized)


@dataclass(frozen=True)
class NetworkSnapshot:
    exchange: str
    asset: str
    observed_at: float
    networks: Tuple[NetworkStatus, ...]

    def is_fresh(self, now: float, max_age_seconds: float) -> bool:
        age = now - self.observed_at
        return 0 <= age <= max_age_seconds


@dataclass(frozen=True)
class ApiPermissionSnapshot:
    exchange: str
    observed_at: float
    can_read: bool
    can_spot_trade: bool
    can_withdraw: bool

    def is_fresh(self, now: float, max_age_seconds: float) -> bool:
        age = now - self.observed_at
        return 0 <= age <= max_age_seconds


@dataclass(frozen=True)
class BalanceSnapshot:
    exchange: str
    base_available: Decimal
    quote_available: Decimal


@dataclass(frozen=True)
class LiveReadinessReport:
    ready: bool
    checked_at: float
    reasons: Tuple[str, ...]
    common_rebalance_networks: Tuple[str, ...] = ()


def _fee_in_quote(fee_asset: Decimal, asset_quote_price: Decimal) -> Decimal:
    if fee_asset <= 0:
        return Decimal("0")
    if asset_quote_price <= 0:
        return Decimal("Infinity")
    return fee_asset * asset_quote_price


def parse_binance_network_statuses(
    payload,
    asset: str,
    asset_quote_price: Decimal,
) -> Tuple[NetworkStatus, ...]:
    asset = asset.upper()
    rows = payload if isinstance(payload, list) else []
    coin = next((row for row in rows if str(row.get("coin", "")).upper() == asset), None)
    if not coin:
        return ()

    result = []
    for network in coin.get("networkList", []) or []:
        fee_asset = _d(network.get("withdrawFee"))
        result.append(
            NetworkStatus(
                network=str(network.get("network") or network.get("name") or ""),
                deposit_enabled=network.get("depositEnable") if isinstance(network.get("depositEnable"), bool) else None,
                withdrawal_enabled=network.get("withdrawEnable") if isinstance(network.get("withdrawEnable"), bool) else None,
                withdrawal_fee_quote=_fee_in_quote(fee_asset, asset_quote_price),
            )
        )
    return tuple(item for item in result if item.network)


def parse_kucoin_network_statuses(
    payload,
    asset: str,
    asset_quote_price: Decimal,
) -> Tuple[NetworkStatus, ...]:
    asset = asset.upper()
    data = payload.get("data") if isinstance(payload, dict) else None

    if isinstance(data, list):
        data = next((row for row in data if str(row.get("currency", "")).upper() == asset), None)
    if not isinstance(data, dict) or str(data.get("currency", asset)).upper() != asset:
        return ()

    chains = data.get("chains")
    if chains is None:
        chains = data.get("list")
    if chains is None:
        chains = data.get("items")
    chains = chains or []

    result = []
    for chain in chains:
        fee_asset = _d(
            chain.get("withdrawalMinFee")
            if chain.get("withdrawalMinFee") is not None
            else chain.get("withdrawMinFee")
            if chain.get("withdrawMinFee") is not None
            else chain.get("minWithdrawFee")
        )
        result.append(
            NetworkStatus(
                network=str(chain.get("chainName") or chain.get("chain") or chain.get("chainId") or ""),
                deposit_enabled=chain.get("isDepositEnabled") if isinstance(chain.get("isDepositEnabled"), bool) else None,
                withdrawal_enabled=chain.get("isWithdrawEnabled") if isinstance(chain.get("isWithdrawEnabled"), bool) else None,
                withdrawal_fee_quote=_fee_in_quote(fee_asset, asset_quote_price),
            )
        )
    return tuple(item for item in result if item.network)


def parse_binance_permissions(payload, observed_at: float) -> ApiPermissionSnapshot:
    payload = payload if isinstance(payload, dict) else {}
    return ApiPermissionSnapshot(
        exchange="binance",
        observed_at=observed_at,
        can_read=payload.get("enableReading") is True,
        can_spot_trade=payload.get("enableSpotAndMarginTrading") is True,
        can_withdraw=payload.get("enableWithdrawals") is True,
    )


def parse_kucoin_permissions(payload, observed_at: float) -> ApiPermissionSnapshot:
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    raw_permissions = data.get("permission", "")
    tokens = {item.strip().lower() for item in str(raw_permissions).split(",") if item.strip()}
    return ApiPermissionSnapshot(
        exchange="kucoin",
        observed_at=observed_at,
        can_read="general" in tokens,
        can_spot_trade="spot" in tokens or "unified" in tokens,
        # KuCoin has used both Withdrawal and Transfer naming for withdrawal-capable keys.
        can_withdraw="withdrawal" in tokens or "withdraw" in tokens or "transfer" in tokens,
    )


def _binance_sapi_url(connector, path: str) -> str:
    return f"https://api.binance.{connector.domain}{path}"


async def fetch_network_snapshot(
    connector_name: str,
    connector,
    asset: str,
    asset_quote_price: Decimal,
    observed_at: float,
) -> NetworkSnapshot:
    exchange = connector_name.removesuffix("_paper_trade")
    if exchange == "binance":
        payload = await connector._api_get(
            path_url=BINANCE_ALL_COINS_PATH,
            overwrite_url=_binance_sapi_url(connector, BINANCE_ALL_COINS_PATH),
            is_auth_required=True,
            limit_id=BINANCE_ALL_COINS_PATH,
        )
        networks = parse_binance_network_statuses(payload, asset, asset_quote_price)
    elif exchange == "kucoin":
        path = KUCOIN_CURRENCY_PATH_TEMPLATE.format(asset=asset.upper())
        payload = await connector._api_get(
            path_url=path,
            is_auth_required=False,
            limit_id=KUCOIN_CURRENCY_PATH_TEMPLATE,
        )
        networks = parse_kucoin_network_statuses(payload, asset, asset_quote_price)
    else:
        raise ValueError(f"Unsupported live network-status adapter: {connector_name}")

    return NetworkSnapshot(
        exchange=exchange,
        asset=asset.upper(),
        observed_at=observed_at,
        networks=networks,
    )


async def fetch_api_permissions(
    connector_name: str,
    connector,
    observed_at: float,
) -> ApiPermissionSnapshot:
    exchange = connector_name.removesuffix("_paper_trade")
    if exchange == "binance":
        payload = await connector._api_get(
            path_url=BINANCE_API_RESTRICTIONS_PATH,
            overwrite_url=_binance_sapi_url(connector, BINANCE_API_RESTRICTIONS_PATH),
            is_auth_required=True,
            limit_id=BINANCE_API_RESTRICTIONS_PATH,
        )
        return parse_binance_permissions(payload, observed_at)
    if exchange == "kucoin":
        payload = await connector._api_get(
            path_url=KUCOIN_API_KEY_INFO_PATH,
            is_auth_required=True,
            limit_id=KUCOIN_API_KEY_INFO_PATH,
        )
        return parse_kucoin_permissions(payload, observed_at)
    raise ValueError(f"Unsupported live permission adapter: {connector_name}")


def _fully_enabled_network_names(snapshot: NetworkSnapshot) -> set:
    return {
        _canonical_network(item.network)
        for item in snapshot.networks
        if item.deposit_enabled is True and item.withdrawal_enabled is True
    }


def common_bidirectional_rebalance_networks(snapshots: Sequence[NetworkSnapshot]) -> Tuple[str, ...]:
    if not snapshots:
        return ()
    sets = [_fully_enabled_network_names(snapshot) for snapshot in snapshots]
    return tuple(sorted(set.intersection(*sets))) if sets else ()


def assess_live_readiness(
    connector_names: Sequence[str],
    trading_pair: str,
    total_amount_quote: Decimal,
    asset_quote_price: Decimal,
    connector_ready: Mapping[str, bool],
    permissions: Mapping[str, ApiPermissionSnapshot],
    network_snapshots: Mapping[str, NetworkSnapshot],
    balances: Mapping[str, BalanceSnapshot],
    now: float,
    max_age_seconds: float = 120,
) -> LiveReadinessReport:
    reasons = []
    base_asset, quote_asset = trading_pair.split("-")

    if len(connector_names) != 2 or connector_names[0] == connector_names[1]:
        reasons.append("exactly two different live connectors are required")

    for name in connector_names:
        if name.endswith("_paper_trade"):
            reasons.append(f"{name}: paper connector is not allowed in live readiness")
            continue
        if connector_ready.get(name) is not True:
            reasons.append(f"{name}: connector is not ready")

        permission = permissions.get(name)
        if permission is None:
            reasons.append(f"{name}: API permission status unavailable")
        else:
            if not permission.is_fresh(now, max_age_seconds):
                reasons.append(f"{name}: API permission status is stale")
            if not permission.can_read:
                reasons.append(f"{name}: API key lacks read permission")
            if not permission.can_spot_trade:
                reasons.append(f"{name}: API key lacks spot-trading permission")
            if permission.can_withdraw:
                reasons.append(f"{name}: API withdrawal permission must be disabled")

        network_snapshot = network_snapshots.get(name)
        if network_snapshot is None:
            reasons.append(f"{name}: {base_asset} network status unavailable")
        else:
            if not network_snapshot.is_fresh(now, max_age_seconds):
                reasons.append(f"{name}: {base_asset} network status is stale")
            if not network_snapshot.networks:
                reasons.append(f"{name}: no {base_asset} network data returned")

        balance = balances.get(name)
        if balance is None:
            reasons.append(f"{name}: balance status unavailable")
        else:
            if balance.quote_available < total_amount_quote:
                reasons.append(
                    f"{name}: insufficient {quote_asset} for configured trade cap "
                    f"({balance.quote_available} < {total_amount_quote})"
                )
            if asset_quote_price <= 0:
                reasons.append("base/quote conversion price unavailable")
            elif balance.base_available * asset_quote_price < total_amount_quote:
                reasons.append(
                    f"{name}: insufficient {base_asset} for reverse arbitrage direction"
                )

    available_network_snapshots = [
        network_snapshots[name]
        for name in connector_names
        if name in network_snapshots and network_snapshots[name].is_fresh(now, max_age_seconds)
    ]
    common_networks = common_bidirectional_rebalance_networks(available_network_snapshots)
    if len(available_network_snapshots) == len(connector_names) and not common_networks:
        reasons.append(f"no common bidirectional {base_asset} deposit/withdraw network")

    # Deduplicate while preserving deterministic order.
    reasons = list(dict.fromkeys(reasons))
    return LiveReadinessReport(
        ready=len(reasons) == 0,
        checked_at=now,
        reasons=tuple(reasons),
        common_rebalance_networks=common_networks,
    )


async def collect_live_readiness(
    market_data_provider,
    connector_names: Sequence[str],
    trading_pair: str,
    total_amount_quote: Decimal,
    quote_conversion_asset: str,
    max_age_seconds: float = 120,
) -> LiveReadinessReport:
    now = market_data_provider.time()
    base_asset, quote_asset = trading_pair.split("-")
    if quote_asset != quote_conversion_asset:
        return LiveReadinessReport(
            ready=False,
            checked_at=now,
            reasons=(f"live readiness currently requires quote asset {quote_conversion_asset}, got {quote_asset}",),
        )

    asset_quote_price = market_data_provider.get_rate(f"{base_asset}-{quote_conversion_asset}")
    asset_quote_price = _d(asset_quote_price)
    connectors: Dict[str, object] = {}
    connector_ready: Dict[str, bool] = {}
    balances: Dict[str, BalanceSnapshot] = {}

    for name in connector_names:
        try:
            connector = market_data_provider.get_connector(name)
            connectors[name] = connector
            connector_ready[name] = bool(connector.ready)
            balances[name] = BalanceSnapshot(
                exchange=name,
                base_available=_d(connector.get_available_balance(base_asset)),
                quote_available=_d(connector.get_available_balance(quote_asset)),
            )
        except Exception:
            connector_ready[name] = False

    permissions: Dict[str, ApiPermissionSnapshot] = {}
    network_snapshots: Dict[str, NetworkSnapshot] = {}

    async def collect_for(name: str):
        connector = connectors.get(name)
        if connector is None:
            return name, None, None
        try:
            permission, networks = await asyncio.gather(
                fetch_api_permissions(name, connector, now),
                fetch_network_snapshot(name, connector, base_asset, asset_quote_price, now),
            )
            return name, permission, networks
        except Exception:
            return name, None, None

    results = await asyncio.gather(*(collect_for(name) for name in connector_names))
    for name, permission, networks in results:
        if permission is not None:
            permissions[name] = permission
        if networks is not None:
            network_snapshots[name] = networks

    return assess_live_readiness(
        connector_names=connector_names,
        trading_pair=trading_pair,
        total_amount_quote=total_amount_quote,
        asset_quote_price=asset_quote_price,
        connector_ready=connector_ready,
        permissions=permissions,
        network_snapshots=network_snapshots,
        balances=balances,
        now=now,
        max_age_seconds=max_age_seconds,
    )
