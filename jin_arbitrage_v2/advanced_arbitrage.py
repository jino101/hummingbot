"""Paper-only scanners for additional arbitrage families."""
from dataclasses import dataclass

@dataclass(frozen=True)
class RouteResult:
    strategy:str; route:tuple; gross_pct:float; net_pct:float; size_usd:float
    @property
    def estimated_profit_usd(self): return self.size_usd*self.net_pct/100

def scan_cycle(rates, route, fee_pct=0.1, size_usd=25.0, min_net_pct=0.0):
    if len(route)<3 or route[0]!=route[-1]:return None
    mult=1.0
    for a,b in zip(route,route[1:]):
        rate=float(rates.get((a,b),0) or 0)
        if rate<=0:return None
        mult*=rate
    gross=(mult-1)*100; net=gross-fee_pct*(len(route)-1)
    if net<min_net_pct:return None
    name="quadrangular" if len(route)==5 else "multi_leg"
    return RouteResult(name,tuple(route),gross,net,size_usd)

def funding_arbitrage(spot_price, perp_price, funding_pct, fee_pct=0.1, size_usd=25.0):
    spot=float(spot_price); perp=float(perp_price)
    if spot<=0 or perp<=0:return None
    basis=(perp/spot-1)*100
    # Research estimate: positive funding favors long spot/short perp.
    net=basis+float(funding_pct)-2*float(fee_pct)
    side="long_spot_short_perp" if net>=0 else "short_spot_long_perp"
    return {"strategy":"funding","side":side,"basis_pct":basis,"estimated_net_pct":abs(net),"size_usd":size_usd}

def cash_and_carry(spot_price,future_price,days_to_expiry,fee_pct=0.1,size_usd=25.0):
    spot=float(spot_price); future=float(future_price); days=float(days_to_expiry)
    if spot<=0 or future<=0 or days<=0:return None
    carry=(future/spot-1)*100-2*float(fee_pct)
    annualized=carry*365/days
    return {"strategy":"cash_and_carry","net_pct":carry,"annualized_pct":annualized,"size_usd":size_usd}
