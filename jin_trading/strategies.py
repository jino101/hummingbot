"""Bounded paper spot strategies and explicit capital-growth stages."""
from collections import deque
from decimal import Decimal, ROUND_DOWN

from jin_trading.arbitrage import number

STRATEGIES=('triangular','cross_exchange','momentum','mean_reversion','grid')


def growth(equity):
    equity=number(equity)
    if equity<0:raise ValueError('Negative equity')
    stages=[Decimal(x) for x in ('5','10','25','50','100','250','500','1000')]
    return {'stage':str(max((s for s in stages if s<=equity),default=Decimal('0'))),
            'next_stage':next((str(s) for s in stages if s>equity),None),
            'max_deployment':str(equity*Decimal('.5')),'stress_budget':str(equity*Decimal('.01')),
            'daily_loss_limit':str(equity*Decimal('.1')),
            'policy':'Amounts grow with equity; risk percentages never increase automatically'}


class Signals:
    def __init__(self, kind, window=20, threshold='.01', stop='.02', take='.03'):
        if kind not in STRATEGIES[2:] or not 3<=window<=500:raise ValueError('Invalid strategy/window')
        self.kind,self.prices=kind,deque(maxlen=window)
        self.threshold,self.stop,self.take=map(number,(threshold,stop,take))
        if not all(0<x<1 for x in (self.threshold,self.stop,self.take)):raise ValueError('Invalid signal bounds')

    def signal(self, book, wallet, equity, entries=None):
        base,quote=book.assets
        if quote!='USDT':raise ValueError('USDT strategy market required')
        bid,ask=book.bids[0][0],book.asks[0][0]
        self.prices.append((bid+ask)/2)
        held=number(wallet.get(base,0))
        if len(self.prices)<self.prices.maxlen:return None
        reference=sum(self.prices,Decimal('0'))/len(self.prices)
        move=(bid-reference)/reference
        # Inventory is marked every tick, including while a strategy is paused.
        if held:
            entry=number((entries or {}).get(base,reference))
            change=(bid-entry)/entry
            exit_signal=change<=-self.stop or change>=self.take
            if self.kind in ('mean_reversion','grid'):exit_signal=exit_signal or bid>=reference*(1+self.threshold)
            if self.kind=='momentum':exit_signal=exit_signal or move<0
            quantity=(held/book.step).to_integral_value(rounding=ROUND_DOWN)*book.step
            return ('sell',quantity) if exit_signal and quantity>=book.min_size and quantity*bid>=book.min_notional else None
        enter=(move>=self.threshold if self.kind=='momentum' else move<=-self.threshold)
        if not enter:return None
        # 1% modeled stop-loss budget, accounting for fees and slippage buffers.
        fraction=min(Decimal('.5'),Decimal('.01')/(self.stop+2*book.fee+Decimal('.002')))
        budget=min(number(wallet.get(quote,0)),number(equity)*fraction)
        quantity=(budget/(ask*(1+book.fee)*Decimal('1.001'))/book.step).to_integral_value(rounding=ROUND_DOWN)*book.step
        if quantity<book.min_size or quantity>book.max_size or quantity*ask<book.min_notional:return None
        return 'buy',quantity
