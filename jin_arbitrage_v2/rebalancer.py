from dataclasses import dataclass
from typing import Dict,List

@dataclass
class RebalanceAction:
    venue:str; asset:str; current:float; target:float; delta:float

def plan_rebalance(balances:Dict[str,Dict[str,float]], targets:Dict[str,Dict[str,float]], tolerance=0.05)->List[RebalanceAction]:
    out=[]
    for venue,assets in targets.items():
        for asset,target in assets.items():
            cur=balances.get(venue,{}).get(asset,0.0)
            delta=target-cur
            if target and abs(delta)/target >= tolerance:
                out.append(RebalanceAction(venue,asset,cur,target,delta))
    return out
