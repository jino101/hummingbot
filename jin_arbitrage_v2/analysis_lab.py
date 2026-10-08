"""Network-free analytics used by the paper/research layer."""
from math import sqrt

def portfolio_metrics(returns):
    xs=[float(x) for x in returns]
    if not xs:return {"mean":0.0,"volatility":0.0,"sharpe":0.0,"max_drawdown":0.0}
    mean=sum(xs)/len(xs)
    var=sum((x-mean)**2 for x in xs)/max(1,len(xs)-1); vol=sqrt(var)
    equity=1.0; peak=1.0; max_dd=0.0
    for r in xs:
        equity*=1+r; peak=max(peak,equity); max_dd=max(max_dd,(peak-equity)/peak)
    return {"mean":mean,"volatility":vol,"sharpe":0.0 if vol==0 else mean/vol,"max_drawdown":max_dd}

def rank_yields(items, min_tvl_usd=100000):
    valid=[dict(x) for x in items if float(x.get("tvl_usd",0) or 0)>=min_tvl_usd and float(x.get("apy",0) or 0)>=0]
    return sorted(valid,key=lambda x:float(x.get("apy",0)),reverse=True)

def liquidation_pressure(events):
    longs=sum(float(e.get("usd",0) or 0) for e in events if e.get("side")=="long")
    shorts=sum(float(e.get("usd",0) or 0) for e in events if e.get("side")=="short")
    total=longs+shorts
    return {"long_usd":longs,"short_usd":shorts,"imbalance":0.0 if total==0 else (longs-shorts)/total}

def anomaly_score(value, history):
    xs=[float(x) for x in history]
    if len(xs)<5:return 0.0
    m=sum(xs)/len(xs); var=sum((x-m)**2 for x in xs)/max(1,len(xs)-1); sd=sqrt(var)
    return 0.0 if sd==0 else (float(value)-m)/sd

def onchain_flow(transfers):
    inflow=sum(float(t.get("usd",0) or 0) for t in transfers if t.get("direction")=="in")
    outflow=sum(float(t.get("usd",0) or 0) for t in transfers if t.get("direction")=="out")
    return {"inflow_usd":inflow,"outflow_usd":outflow,"net_flow_usd":inflow-outflow}
