"""Explicitly configured autonomous spot runner using the durable supervisor.

Separate database and entry point; the normal server always remains paper-only.
Real account activation is performed locally by the operator, never through a
configuration checkbox in the default dashboard.
"""
import argparse
import hashlib
import json
import os
import threading
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from jin_trading.arbitrage import number,scan_with_diagnostics
from jin_trading.brokers import SpotBroker
from jin_trading.feeds import PublicFeed
from jin_trading.server import make_server
from jin_trading.store import Store
from jin_trading.supervisor import Portfolio
from jin_trading.execution import ExecutionEngine
from jin_trading.worker import Worker, validate_config


class LiveWorker(Worker):
    def __init__(self,store,config,clients,activated=False):
        if not activated:raise ValueError('Explicit local live activation required')
        validate_config(config,'live')
        if set(clients)!=set(config.get('fees',{})):raise ValueError('Every configured account requires a client')
        if set(clients)!={spec['exchange'] for spec in config['bots'].values()}:
            raise ValueError('Every live account requires an explicit bot allocation')
        for name,spec in config['bots'].items():
            if spec['exchange'] not in clients or spec.get('strategy','triangular')!='triangular':
                raise ValueError('Autonomous live runner currently supports triangular spot strategies')
        if not 0<number(config['max_deploy_fraction'])<=Decimal('.5'):raise ValueError('Invalid deployment limit')
        if not Decimal('.001')<=number(config['slippage'])<Decimal('.05'):raise ValueError('Invalid slippage')
        if not 0<float(config['max_age'])<=3 or not 2<=float(config['poll_seconds'])<=60:raise ValueError('Invalid data timing')
        self.store,self.config=store,config;self.stop=threading.Event();self.batch_index=0
        self.feeds={name:PublicFeed(name,fee) for name,fee in config['fees'].items()}
        self.portfolio=Portfolio(store.path,'live');self.portfolio.register(clients)
        self.brokers={name:SpotBroker(client,self.feeds[name],armed=True) for name,client in clients.items()}
        self.engine=ExecutionEngine(self.portfolio,self.brokers,config['max_age'],number(config['slippage']),config['min_profit'])
        self.universe_status={'mode':config.get('pair_mode','auto'),'live_activated_locally':True}
        self.signals={};self.last_sync=0

    def sync_accounts(self):
        equities={};errors=[]
        for account,broker in self.brokers.items():
            try:equities[account]=number(broker.sync(self.portfolio,account)['equity'])
            except Exception as exc:
                self.portfolio.invalidate_account(account);errors.append(account+': '+type(exc).__name__)
        # Display allocations of the same account without duplicating equity.
        allocations={}
        with self.store.connect() as db:
            initialized=self.store._get(db,'actual_allocation_initialized')=='1'
        for account,equity in equities.items():
            bots={name:spec for name,spec in self.config['bots'].items() if spec['exchange']==account}
            weight=sum((number(s['budget']) for s in bots.values()),Decimal('0'))
            if not initialized and equity>weight*Decimal('1.01'):
                self.portfolio.halt('Actual account equity exceeds the configured starting allocation')
                errors.append(account+': account equity exceeds the configured starting allocation')
                continue
            for name,spec in bots.items():allocations[name]=equity*number(spec['budget'])/weight
        if not errors and self.portfolio.snapshot()['ready']:
            self.store.mark_equities(allocations,initialize_actual=True)
        self.last_sync=time.time()
        return errors

    def tick(self):
        errors=self.sync_accounts()
        if errors:
            self.engine.stop_all();self.process_books([],errors);return
        self.engine.reconcile()
        if self.portfolio.orders(True):
            self.portfolio.halt('Unsettled execution requires inventory review')
        super().tick()

    def process_books(self,books,errors):
        state=self.store.snapshot()
        if state['halt']:self.engine.stop_all()
        ready=self.portfolio.snapshot()['ready'] and not state['halt']
        for bot in state['bots']:
            spec=self.config['bots'][bot['id']];account=spec['exchange'];broker=self.brokers[account]
            usable=[]
            for book in books:
                if book.exchange!=account:continue
                verified=broker.verified_fees.get(book.pair)
                if not verified or not 0<=time.time()-verified[0]<=120:
                    try:
                        fee=number(broker.client.fetch_trading_fee(book.pair.replace('-','/'))['taker'])
                        if not 0<=fee<1:raise ValueError('Invalid account fee')
                        broker.verified_fees[book.pair]=(time.time(),fee)
                    except Exception as exc:errors=list(errors)+[book.pair+': fee '+type(exc).__name__];continue
                from dataclasses import replace
                usable.append(replace(book,fee=broker.verified_fees[book.pair][1]))
            amount=number(bot['capital'])*number(self.config['max_deploy_fraction'])
            opportunities,near,rejected=scan_with_diagnostics(usable,amount,time.time(),max_age=self.config['max_age'],
                min_profit=number(self.config['min_profit']),slippage=number(self.config['slippage']))
            eligible=[o for o in opportunities if o.kind=='triangular']
            if eligible and bot['enabled'] and ready:
                o=eligible[0];run=hashlib.sha256((bot['id']+o.sequence).encode()).hexdigest()
                try:
                    result=self.engine.triangle(bot['id'],account,[p for _,p in o.route],amount,run)
                    self.store.record_execution(bot['id'],o,result)
                    errors=list(errors)+self.sync_accounts()
                except Exception as exc:
                    errors=list(errors)+[bot['id']+': '+type(exc).__name__]
                ready=self.portfolio.snapshot()['ready'] and not self.store.snapshot()['halt']
            self.store.publish(bot['id'],{'feed':'live REST; verified account fees','execution':'LIVE shared order journal',
                'books_received':len(usable),'errors':errors,'universe':self.universe_status,
                'opportunities':[asdict(o)|{'net_fraction':str(o.net_fraction)} for o in opportunities[:20]],
                'near_misses':[asdict(o)|{'reason':reason,'net_fraction':str(o.net_fraction)} for o,reason in near],
                'rejected_counts':rejected,'updated_at':time.time()})


def main():
    parser=argparse.ArgumentParser(description='Operator-only autonomous live spot runner; separate from paper')
    parser.add_argument('--config',required=True);parser.add_argument('--db',default='data/jin-live.sqlite')
    parser.add_argument('--activate-live',required=True,choices=['I_UNDERSTAND_LIVE_ORDERS'])
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8790)
    args=parser.parse_args()
    with open(args.config) as stream:config=validate_config(json.load(stream),'live')
    import ccxt
    clients={}
    for name in config['fees']:
        prefix='JIN_'+name.upper()+'_';key,secret=os.environ.get(prefix+'KEY'),os.environ.get(prefix+'SECRET')
        if not key or not secret:parser.error('Missing local credentials for '+name)
        client=getattr(ccxt,name)({'apiKey':key,'secret':secret,'password':os.environ.get(prefix+'PASSPHRASE'),
            'enableRateLimit':True,'timeout':8000,'options':{'defaultType':'spot'}})
        client.load_markets();clients[name]=client
    Path(args.db).parent.mkdir(parents=True,exist_ok=True)
    store=Store(args.db);store.configure({b:s['budget'] for b,s in config['bots'].items()})
    worker=LiveWorker(store,config,clients,True)
    if worker.sync_accounts() or not worker.portfolio.snapshot()['ready']:
        parser.error('Live preflight failed; review the journal and verified account permissions')
    server=make_server(store,os.environ.get('JIN_DASHBOARD_TOKEN',''),args.host,args.port,worker=worker,
                       allowed_origins=config.get('allowed_origins',()))
    threading.Thread(target=worker.run,daemon=True).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:worker.stop.set();worker.engine.stop_all();server.server_close()


if __name__=='__main__':main()
