"""Complete USDT-connected spot universe, scheduled in bounded route-complete batches."""
from collections import defaultdict


def route_groups(pairs, start="USDT"):
    edges = defaultdict(list)
    for pair in sorted(set(pairs)):
        base, quote = pair.split("-")
        if base == quote or not base or not quote:
            raise ValueError("Invalid pair")
        edges[base].append((quote, pair))
        edges[quote].append((base, pair))
    groups = {tuple([pair]) for _, pair in edges[start]}
    closing = defaultdict(list)
    for asset, pair in edges[start]:
        closing[asset].append(pair)
    for first, p1 in edges[start]:
        for second, p2 in edges[first]:
            if second in (start, first):
                continue
            for p3 in closing[second]:
                groups.add(tuple(sorted((p1, p2, p3))))
    return sorted(groups, key=lambda group: (-len(group), group))


def plan_batches(venue_pairs, batch_size=12, denied=()):
    """All supported USDT pairs and triangles; no arbitrary coin-count cap.

    Never construct a triangle from edges on different exchanges.
    A singleton also supplies cross-exchange comparison when shared by venues.
    """
    if not 3 <= batch_size <= 20:
        raise ValueError("Batch size must be 3–20")
    denied = set(denied)
    groups = set()
    for pairs in venue_pairs.values():
        groups.update(route_groups(set(pairs) - denied))
    batches, current = [], set()
    for group in sorted(groups, key=lambda group: (-len(group), group)):
        if len(current | set(group)) > batch_size:
            batches.append(tuple(sorted(current)))
            current = set()
        current.update(group)
    if current:
        batches.append(tuple(sorted(current)))
    return batches
