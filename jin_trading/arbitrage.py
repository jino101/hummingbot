"""Depth-aware, conservative spot estimates. No order submission occurs here."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from itertools import permutations
from typing import Tuple
from collections import defaultdict, Counter


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite number")
    return result


@dataclass(frozen=True)
class Book:
    exchange: str
    pair: str
    bids: Tuple[Tuple[Decimal, Decimal], ...]
    asks: Tuple[Tuple[Decimal, Decimal], ...]
    timestamp: float
    sequence: str
    fee: Decimal
    step: Decimal
    min_size: Decimal
    min_notional: Decimal
    max_size: Decimal = Decimal("1e50")

    def __post_init__(self):
        base, quote = self.pair.split("-")
        if not base or not quote or base == quote:
            raise ValueError("Invalid pair")
        if not 0 <= self.fee < 1 or self.step <= 0 or self.min_size < 0 or self.min_notional < 0:
            raise ValueError("Invalid trading rules")
        for value in (self.fee, self.step, self.min_size, self.min_notional, self.max_size):
            number(value)
        for side in (self.bids, self.asks):
            if not side or any(number(p) <= 0 or number(q) <= 0 for p, q in side):
                raise ValueError("Invalid order book")
        if list(self.bids) != sorted(self.bids, reverse=True) or list(self.asks) != sorted(self.asks):
            raise ValueError("Unsorted book")
        if self.bids[0][0] >= self.asks[0][0]:
            raise ValueError("Crossed book")
        number(self.timestamp)

    @property
    def assets(self):
        return self.pair.split("-")

    def convert(self, source, amount, slippage=Decimal("0.001")):
        """Walk depth, round quantity down, enforce minimums; discard residual dust."""
        amount = number(amount)
        if amount <= 0 or not 0 <= slippage < 1:
            raise ValueError("Invalid amount/slippage")
        base, quote = self.assets
        if source == base:
            quantity = (amount / self.step).to_integral_value(rounding=ROUND_DOWN) * self.step
            remaining, proceeds = quantity, Decimal("0")
            for price, available in self.bids:
                used = min(remaining, available)
                proceeds += used * price
                remaining -= used
                if remaining == 0:
                    break
            notional = proceeds
            output = proceeds * (1 - self.fee) * (1 - slippage)
            target = quote
        elif source == quote:
            remaining, raw_quantity = amount, Decimal("0")
            for price, available in self.asks:
                used = min(available, remaining / (price * (1 + slippage)))
                raw_quantity += used
                remaining -= used * price * (1 + slippage)
                if remaining <= Decimal("1e-24"):
                    break
            if remaining > Decimal("1e-24"):
                raise ValueError("Insufficient depth")
            quantity = (raw_quantity / self.step).to_integral_value(rounding=ROUND_DOWN) * self.step
            left, notional = quantity, Decimal("0")
            for price, available in self.asks:
                used = min(left, available)
                notional += used * price
                left -= used
                if left == 0:
                    break
            remaining = left
            output = quantity * (1 - self.fee)
            target = base
        else:
            raise ValueError("Source asset does not belong to pair")
        if remaining > Decimal("1e-24"):
            raise ValueError("Insufficient depth")
        if quantity <= 0 or not self.min_size <= quantity <= self.max_size or notional < self.min_notional:
            raise ValueError("Order outside exchange limits")
        return target, output


@dataclass(frozen=True)
class Opportunity:
    kind: str
    route: tuple
    input_amount: Decimal
    output_amount: Decimal
    sequence: str

    @property
    def profit(self):
        return self.output_amount - self.input_amount

    @property
    def net_fraction(self):
        return self.profit / self.input_amount


def _prepare(books, now, start_asset, max_age):
    fresh = [b for b in books if 0 <= now - b.timestamp <= max_age]
    adjacency = defaultdict(lambda: defaultdict(list))
    quoted = defaultdict(list)
    for book in fresh:
        for asset in book.assets:
            adjacency[book.exchange][asset].append(book)
        if book.assets[1] == start_asset:
            quoted[book.pair].append(book)
    return fresh, adjacency, quoted


def _triangle_routes(adjacency, start_asset):
    for edges in adjacency.values():
        for first in edges[start_asset]:
            asset = next(a for a in first.assets if a != start_asset)
            for second in edges[asset]:
                if second == first:
                    continue
                middle = next(a for a in second.assets if a != asset)
                if middle == start_asset:
                    continue
                for third in edges[middle]:
                    if start_asset in third.assets:
                        yield first, second, third


def scan_with_diagnostics(books, amount, now, start_asset="USDT", max_age=3.0,
                          min_profit=Decimal("0.0035"), slippage=Decimal("0.001"),
                          near_limit=5):
    """Return executable estimates plus best valid routes below threshold and rejection counts."""
    amount = number(amount)
    min_profit = number(min_profit)
    if amount <= 0 or max_age <= 0 or near_limit < 1:
        raise ValueError("Invalid scan settings")
    _, adjacency, quoted = _prepare(books, now, start_asset, max_age)
    accepted, below = [], []
    rejected = Counter()

    for route in _triangle_routes(adjacency, start_asset):
        asset, output = start_asset, amount
        visited = [asset]
        try:
            for book in route:
                asset, output = book.convert(asset, output, slippage)
                visited.append(asset)
        except ValueError as exc:
            rejected[str(exc)] += 1
            continue
        if asset != start_asset or len(set(visited[:-1])) != 3:
            rejected["Route does not close to three distinct assets"] += 1
            continue
        item = Opportunity("triangular", tuple((b.exchange, b.pair) for b in route), amount, output,
                           "|".join(f"{b.exchange}:{b.pair}:{b.sequence}" for b in route))
        if item.net_fraction >= min_profit:
            accepted.append(item)
        else:
            below.append((item, f"unter Mindestgewinn {min_profit * 100:.3f} %"))

    for buy, sell in (route for matches in quoted.values() for route in permutations(matches, 2)):
        if buy.exchange == sell.exchange:
            continue
        try:
            base, quantity = buy.convert(start_asset, amount, slippage)
            _, output = sell.convert(base, quantity, slippage)
        except ValueError as exc:
            rejected[str(exc)] += 1
            continue
        item = Opportunity("cross_exchange", ((buy.exchange, buy.pair), (sell.exchange, sell.pair)),
                           amount, output, f"{buy.exchange}:{buy.sequence}|{sell.exchange}:{sell.sequence}")
        if item.net_fraction >= min_profit:
            accepted.append(item)
        else:
            below.append((item, f"unter Mindestgewinn {min_profit * 100:.3f} %"))

    accepted.sort(key=lambda x: x.net_fraction, reverse=True)
    below.sort(key=lambda x: x[0].net_fraction, reverse=True)
    return accepted, below[:near_limit], dict(rejected)


def scan(books, amount, now, start_asset="USDT", max_age=3.0, min_profit=Decimal("0.0035"),
         slippage=Decimal("0.001")):
    results, _, _ = scan_with_diagnostics(
        books, amount, now, start_asset=start_asset, max_age=max_age,
        min_profit=min_profit, slippage=slippage)
    return results
