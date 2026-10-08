"""Depth-aware triangular paper calculations."""
from dataclasses import dataclass

@dataclass(frozen=True)
class ConversionBook:
    src: str
    dst: str
    levels: tuple
    fee_pct: float = 0.1

def convert(amount, book):
    remaining=float(amount); result=0.0
    if remaining <= 0: return 0.0
    for capacity, rate in book.levels:
        capacity=float(capacity); rate=float(rate)
        if capacity <= 0 or rate <= 0: continue
        used=min(remaining,capacity)
        result += used*rate
        remaining -= used
        if remaining <= 1e-12: break
    if remaining > 1e-12: return 0.0
    return result*(1.0-max(0.0,float(book.fee_pct))/100.0)

def scan_triangle_depth(venue,start_asset,start_amount,books,min_net_pct=.35):
    if start_amount <= 0: return []
    assets={asset for edge in books for asset in edge}
    output=[]
    for mid1 in assets:
        if mid1 == start_asset: continue
        for mid2 in assets:
            if mid2 in (start_asset,mid1): continue
            edges=((start_asset,mid1),(mid1,mid2),(mid2,start_asset))
            if any(edge not in books for edge in edges): continue
            value=float(start_amount)
            for edge in edges:
                value=convert(value,books[edge])
                if not value: break
            if not value: continue
            net_pct=(value/start_amount-1.0)*100.0
            if net_pct >= min_net_pct:
                output.append({"venue":venue,"route":[start_asset,mid1,mid2,start_asset],
                               "start_amount":start_amount,"final_amount":value,
                               "net_pct":net_pct})
    return sorted(output,key=lambda x:x["net_pct"],reverse=True)
