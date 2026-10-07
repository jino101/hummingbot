"""Read-only local feasibility check. This entry point never creates orders."""
import argparse
import json
import os
import time
from decimal import Decimal

from jin_trading.arbitrage import number,scan
from jin_trading.brokers import SpotBroker
from jin_trading.feeds import PublicFeed
from jin_trading.supervisor import Portfolio
from jin_trading.universe import plan_batches


def check(client,feed,amount='5',db_path='data/jin-live.sqlite'):
    portfolio=Portfolio(db_path,'live');portfolio.register([client.id])
    broker=SpotBroker(client,feed,armed=False)
    account=broker.sync(portfolio,client.id)
    amount=min(number(amount),number(account['free'].get('USDT',0)))
    if amount<=0:return {'mode':'read-only','account':account,'feasible':[],'reason':'No free USDT in spot account'}
    batches=plan_batches({client.id:feed.pairs()},12)
    feasible=[];errors=[]
    for pairs in batches:
        books=[]
        for pair in pairs:
            try:books.append(feed.book(pair))
            except Exception as exc:errors.append(pair+': '+type(exc).__name__)
        for route in scan(books,amount*Decimal('.5'),time.time(),min_profit=Decimal('.0035')):
            if route.kind=='triangular':feasible.append({'route':route.route,'input':str(route.input_amount),
                                                        'estimated_profit':str(route.profit)})
    return {'mode':'read-only','account':account,'checked_pairs':len(feed.pairs()),'feasible':feasible,'errors':errors,
            'reason':'A positive estimate is not proof of executable profit; no order was submitted'}


def main():
    parser=argparse.ArgumentParser(description='Read spot balance, permissions and 5 USDT feasibility; NO orders')
    parser.add_argument('--exchange',choices=['kucoin','binance','bitget'],default='kucoin')
    parser.add_argument('--db',default='data/jin-live.sqlite');parser.add_argument('--amount',default='5')
    args=parser.parse_args()
    try:import ccxt
    except ImportError:parser.error('Install the optional jin_trading/requirements-live.txt first')
    prefix='JIN_'+args.exchange.upper()+'_'
    options={'apiKey':os.environ.get(prefix+'KEY'),'secret':os.environ.get(prefix+'SECRET'),
             'password':os.environ.get(prefix+'PASSPHRASE'),'enableRateLimit':True,'timeout':8000,
             'options':{'defaultType':'spot'}}
    if not options['apiKey'] or not options['secret']:parser.error('Set exchange credentials locally in environment variables')
    client=getattr(ccxt,args.exchange)(options);client.load_markets()
    print(json.dumps(check(client,PublicFeed(args.exchange,'.002'),args.amount,args.db),default=str,indent=2))


if __name__=='__main__':main()
