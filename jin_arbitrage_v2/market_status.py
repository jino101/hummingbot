"""Market and transfer-network compatibility model.

Adapters can populate this from venue APIs later. Unknown status is fail-closed.
"""
from dataclasses import dataclass
from typing import Iterable, Optional

@dataclass(frozen=True)
class NetworkStatus:
    network: str
    deposit: bool
    withdraw: bool
    fee_usd: float = 0.0

@dataclass(frozen=True)
class MarketStatus:
    venue: str
    symbol: str
    active: bool
    networks: tuple = ()

def compatible_transfer_network(buy: MarketStatus, sell: MarketStatus) -> Optional[NetworkStatus]:
    if not buy.active or not sell.active:
        return None
    sell_by_name={n.network.upper():n for n in sell.networks if n.deposit}
    candidates=[]
    for src in buy.networks:
        dst=sell_by_name.get(src.network.upper())
        if src.withdraw and dst:
            candidates.append(NetworkStatus(src.network, True, True, max(src.fee_usd,dst.fee_usd)))
    return min(candidates,key=lambda n:n.fee_usd) if candidates else None

def route_is_transferable(buy: MarketStatus, sell: MarketStatus) -> bool:
    return compatible_transfer_network(buy,sell) is not None
