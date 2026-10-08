from typing import Dict, Iterable, List, Tuple
from .models import Opportunity, StrategyType

def scan_triangles(exchange: str, rates: Dict[Tuple[str,str], float], start_assets: Iterable[str], fee_pct: float = 0.1, size_usd: float = 25.0) -> List[Opportunity]:
    out: List[Opportunity] = []
    assets = set()
    for a,b in rates:
        assets.add(a); assets.add(b)
    for start in start_assets:
        for mid in assets:
            if mid == start: continue
            for end in assets:
                if end in (start, mid): continue
                r1 = rates.get((start, mid))
                r2 = rates.get((mid, end))
                r3 = rates.get((end, start))
                if not all([r1, r2, r3]):
                    continue
                gross_mult = r1 * r2 * r3
                gross_pct = (gross_mult - 1.0) * 100.0
                net_pct = gross_pct - (fee_pct * 3.0)
                if net_pct <= 0:
                    continue
                out.append(Opportunity(
                    strategy=StrategyType.TRIANGULAR,
                    buy_venue=exchange,
                    sell_venue=exchange,
                    symbol=start,
                    gross_pct=gross_pct,
                    net_pct=net_pct,
                    size_usd=size_usd,
                    estimated_profit_usd=size_usd * net_pct / 100.0,
                    route=[start, mid, end, start],
                ))
    out.sort(key=lambda x: x.net_pct, reverse=True)
    return out
