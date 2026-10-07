"""Operator-only one-route executor. Never launched by the paper dashboard.

Defaults to checking accounts. Orders require a literal local activation flag,
verified permissions, verified account fees and the shared durable portfolio.
"""
import argparse
import json
import os
import time
from decimal import Decimal

from jin_trading.arbitrage import number,scan
from jin_trading.brokers import SpotBroker
from jin_trading.execution import ExecutionEngine
from jin_trading.feeds import PublicFeed
from jin_trading.supervisor import Portfolio


def run(clients,exchange,pairs,amount,path,activate=False):
    if exchange not in clients or len(pairs)!=3:raise ValueError('Account and three distinct route markets required')
    portfolio=Portfolio(path,'live');portfolio.register(clients)
    brokers={name:SpotBroker(client,PublicFeed(name,'.002'),armed=activate) for name,client in clients.items()}
    for name,broker in brokers.items():broker.sync(portfolio,name)
    engine=ExecutionEngine(portfolio,brokers,min_profit=Decimal('.0035'))
    reconciliation=engine.reconcile()
    if portfolio.orders(True):
        return {'mode':'blocked','reason':'Unsettled executions require inventory review','reconciliation':reconciliation}
    broker=brokers[exchange];books=[]
    for pair in pairs:
        fee=number(broker.client.fetch_trading_fee(pair.replace('-','/'))['taker'])
        if not 0<=fee<1:raise ValueError('Unverified trading fee')
        broker.verified_fees[pair]=(time.time(),fee)
        broker.feed.fee=fee
        books.append(broker.book(pair))
    opportunities=scan(books,number(amount),time.time(),min_profit=Decimal('.0035'))
    route=next((o for o in opportunities if o.kind=='triangular' and tuple(p for _,p in o.route)==tuple(pairs)),None)
    if not route:return {'mode':'blocked','reason':'No fresh, feasible profitable route in requested order'}
    if not activate:return {'mode':'read-only','route':route.route,'estimated_profit':str(route.profit),'portfolio':portfolio.snapshot()}
    # Refresh every account immediately before reserving; first price lookup never
    # constitutes permission to trade with a stale portfolio snapshot.
    for name,b in brokers.items():b.sync(portfolio,name)
    result=engine.triangle('local-live-once',exchange,pairs,number(amount))
    for name,b in brokers.items():b.sync(portfolio,name)
    return {'mode':'live','result':result,'portfolio':portfolio.snapshot()}


def main():
    parser=argparse.ArgumentParser(description='Read-only by default; optional operator-only ONE live route')
    parser.add_argument('--accounts',nargs='+',choices=['kucoin','binance','bitget'],default=['kucoin'])
    parser.add_argument('--exchange',choices=['kucoin','binance','bitget'],default='kucoin')
    parser.add_argument('--pairs',nargs=3,required=True)
    parser.add_argument('--amount',default='1');parser.add_argument('--db',default='data/jin-live.sqlite')
    parser.add_argument('--activate-live',choices=['I_UNDERSTAND_LIVE_ORDERS'])
    args=parser.parse_args()
    try:import ccxt
    except ImportError:parser.error('Optional CCXT dependency is not installed')
    clients={}
    for exchange in args.accounts:
        prefix='JIN_'+exchange.upper()+'_'
        key,secret=os.environ.get(prefix+'KEY'),os.environ.get(prefix+'SECRET')
        if not key or not secret:parser.error('Missing local credentials for '+exchange)
        client=getattr(ccxt,exchange)({'apiKey':key,'secret':secret,'password':os.environ.get(prefix+'PASSPHRASE'),
                                     'enableRateLimit':True,'timeout':8000,'options':{'defaultType':'spot'}})
        client.load_markets();clients[exchange]=client
    print(json.dumps(run(clients,args.exchange,args.pairs,args.amount,args.db,bool(args.activate_live)),default=str,indent=2))


if __name__=='__main__':main()
