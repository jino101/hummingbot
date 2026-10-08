"""Deterministic paper-only research strategies and backtesting helpers."""
from dataclasses import dataclass
from math import sqrt

@dataclass(frozen=True)
class Signal:
    strategy: str
    side: str
    strength: float
    reason: str

def _series(values):
    out=[float(x) for x in values]
    return out if all(x > 0 for x in out) else []

def mean_reversion(values, window=20, entry_z=2.0):
    x=_series(values)
    if len(x)<window: return None
    s=x[-window:]; m=sum(s)/len(s)
    var=sum((v-m)**2 for v in s)/max(1,len(s)-1); sd=sqrt(var)
    if sd==0:return None
    z=(s[-1]-m)/sd
    if z>=entry_z:return Signal("mean_reversion","sell",abs(z),f"z={z:.3f}")
    if z<=-entry_z:return Signal("mean_reversion","buy",abs(z),f"z={z:.3f}")
    return None

def momentum(values, lookback=20, threshold_pct=1.0):
    x=_series(values)
    if len(x)<=lookback:return None
    pct=(x[-1]/x[-1-lookback]-1)*100
    if abs(pct)<threshold_pct:return None
    return Signal("momentum","buy" if pct>0 else "sell",abs(pct),f"move={pct:.3f}%")

def breakout(values, window=20):
    x=_series(values)
    if len(x)<=window:return None
    prior=x[-window-1:-1]
    if x[-1]>max(prior):return Signal("breakout","buy",x[-1]/max(prior)-1,"new_high")
    if x[-1]<min(prior):return Signal("breakout","sell",min(prior)/x[-1]-1,"new_low")
    return None

def grid_levels(mid, spacing_pct=0.5, levels=3):
    mid=float(mid); step=abs(float(spacing_pct))/100
    if mid<=0 or levels<1:return []
    return [(mid*(1-step*i),mid*(1+step*i)) for i in range(1,int(levels)+1)]

def market_making_quote(mid, spread_pct=0.2, inventory_skew=0.0):
    mid=float(mid); half=abs(float(spread_pct))/200
    skew=max(-1.0,min(1.0,float(inventory_skew)))*half
    return mid*(1-half-skew), mid*(1+half-skew)

def pairs_zscore(left,right,window=30):
    if len(left)<window or len(right)<window:return None
    ratios=[float(a)/float(b) for a,b in zip(left[-window:],right[-window:]) if float(b)>0]
    if len(ratios)<window:return None
    m=sum(ratios)/len(ratios); var=sum((v-m)**2 for v in ratios)/max(1,len(ratios)-1)
    sd=sqrt(var)
    return 0.0 if sd==0 else (ratios[-1]-m)/sd

def simple_backtest(values, signal_fn, fee_pct=0.1):
    x=_series(values)
    cash=0.0; position=0; trades=0
    for i,price in enumerate(x):
        sig=signal_fn(x[:i+1])
        if sig and sig.side=="buy" and position==0:
            position=1; cash-=price*(1+fee_pct/100); trades+=1
        elif sig and sig.side=="sell" and position==1:
            position=0; cash+=price*(1-fee_pct/100); trades+=1
    if position and x: cash+=x[-1]*(1-fee_pct/100)
    return {"pnl":cash,"trades":trades}
