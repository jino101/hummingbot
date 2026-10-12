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


def plan_venue_batches(venue_pairs, batch_size=12, denied=(), required=None):
    """Independent complete-route plans, including valuation markets within 20 slots.

    Required markets remain observable even when denied for new trades. More
    than 17 priorities leave no guaranteed room for an independent triangle;
    expose that limit instead of truncating a trading route.
    """
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 3 <= batch_size <= 20:
        raise ValueError('Batch size must be 3–20')
    required = required or {}
    plans = {}
    for exchange, pairs in venue_pairs.items():
        catalogue = set(pairs)
        priorities = tuple(sorted(set(required.get(exchange, ()))))
        missing = tuple(pair for pair in priorities if pair not in catalogue)
        available = tuple(pair for pair in priorities if pair in catalogue)
        exhausted = len(priorities) > 17
        if exhausted:
            batches = [available[:20]] if available else []
        else:
            capacity = max(batch_size, len(priorities) + 3) - len(priorities)
            rotating = plan_batches({exchange: catalogue}, capacity, denied)
            batches = []
            for batch in rotating:
                # Put a complete group first rather than scattering its legs
                # throughout a lexically sorted REST batch.
                ordered = tuple(dict.fromkeys(pair for group in route_groups(batch) for pair in group))
                batches.append(tuple(dict.fromkeys((*available, *ordered))))
            if not batches and available:
                batches = [available]
        plans[exchange] = {
            'catalogue_pairs': len(catalogue), 'batches': batches,
            'scheduled_pairs': len({pair for batch in batches for pair in batch}),
            'batch_count': len(batches), 'valuation_priority_pairs': priorities,
            'missing_required_pairs': missing, 'capacity_exhausted': exhausted,
        }
    return plans

