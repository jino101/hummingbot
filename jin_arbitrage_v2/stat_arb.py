from collections import deque
from math import sqrt
class ZScoreSpread:
    def __init__(self,window=100):
        self.values=deque(maxlen=window)
    def update(self,spread):
        self.values.append(float(spread))
        if len(self.values)<10:return None
        n=len(self.values); mean=sum(self.values)/n
        var=sum((x-mean)**2 for x in self.values)/(n-1)
        sd=sqrt(var)
        return 0.0 if sd==0 else (spread-mean)/sd
