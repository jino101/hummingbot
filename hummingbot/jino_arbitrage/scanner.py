from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Set

from hummingbot.jino_arbitrage.opportunity import (
    ArbitrageOpportunity,
    VenueQuote,
    find_best_opportunities,
)


def _normalize_pair(pair: str) -> str:
    return pair.strip().upper()


def common_trading_pairs(
    venue_pairs: Dict[str, Iterable[str]],
    allow_pairs: Optional[Iterable[str]] = None,
    deny_pairs: Optional[Iterable[str]] = None,
) -> List[str]:
    """Return spot pairs present on every configured venue.

    Pair matching is case-insensitive and normalized to Hummingbot's BASE-QUOTE
    uppercase format. An allow-list narrows the result; a deny-list always wins.
    """
    if not venue_pairs:
        return []

    normalized_sets: List[Set[str]] = [
        {_normalize_pair(pair) for pair in pairs}
        for pairs in venue_pairs.values()
    ]
    common = set.intersection(*normalized_sets) if normalized_sets else set()

    if allow_pairs is not None:
        common &= {_normalize_pair(pair) for pair in allow_pairs}
    if deny_pairs is not None:
        common -= {_normalize_pair(pair) for pair in deny_pairs}

    return sorted(common)


@dataclass(frozen=True)
class ScannerPolicy:
    min_net_spread_pct: Decimal = Decimal("0")
    estimated_slippage_pct: Decimal = Decimal("0")
    require_rebalance_transferable: bool = False
    allow_pairs: Sequence[str] = ()
    deny_pairs: Sequence[str] = ()


def scan_opportunities(
    quotes: Iterable[VenueQuote],
    requested_amount_base: Decimal,
    policy: ScannerPolicy = ScannerPolicy(),
) -> List[ArbitrageOpportunity]:
    """Rank cross-exchange opportunities under a scanner-only policy.

    This module is deliberately pure: it never submits orders, touches API keys,
    or performs withdrawals. It is suitable for scanner mode and unit tests.
    """
    quote_list = list(quotes)
    allow = {_normalize_pair(pair) for pair in policy.allow_pairs}
    deny = {_normalize_pair(pair) for pair in policy.deny_pairs}

    filtered_quotes = [
        quote
        for quote in quote_list
        if (not allow or _normalize_pair(quote.trading_pair) in allow)
        and _normalize_pair(quote.trading_pair) not in deny
    ]

    opportunities = find_best_opportunities(
        filtered_quotes,
        requested_amount_base=requested_amount_base,
        min_net_spread_pct=policy.min_net_spread_pct,
        estimated_slippage_pct=policy.estimated_slippage_pct,
    )

    if policy.require_rebalance_transferable:
        opportunities = [item for item in opportunities if item.rebalance_transferable]

    return opportunities
