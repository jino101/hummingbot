"""Credential-free CCXT Pro data feed with bounded rotating subscriptions.

The full catalogue is scheduled; at most one bounded batch is subscribed at a
time. This is measured WebSocket observation, not a promise of HFT latency.
"""
import asyncio
import hashlib
import json
import time
from decimal import Decimal

from jin_trading.arbitrage import Book,number
from jin_trading.universe import plan_batches


def snapshot(exchange,pair,raw,rule,fee,received_at=None):
    received_at=time.time() if received_at is None else received_at
    stamp=raw.get('timestamp')
    # A caller may use local receipt only after confirming a changed nonce/data.
    stamp=received_at if stamp is None else float(stamp)/1000
    sequence=str(raw.get('nonce') or hashlib.sha256(json.dumps([raw['bids'],raw['asks']],default=str).encode()).hexdigest())
    step,minimum,notional,maximum=rule
    return Book(exchange,pair,tuple((number(p),number(q)) for p,q,*_ in raw['bids'][:20]),
                tuple((number(p),number(q)) for p,q,*_ in raw['asks'][:20]),stamp,sequence,number(fee),step,minimum,notional,maximum)


class WebSocketRunner:
    def __init__(self,worker,clients,rotation_seconds=15):
        if not 5<=rotation_seconds<=300:raise ValueError('Invalid WebSocket rotation')
        if set(clients)!=set(worker.feeds):raise ValueError('WebSocket clients must match configured exchanges')
        self.worker,self.clients,self.rotation=worker,clients,rotation_seconds
        self.queue=asyncio.Queue(maxsize=200);self.books={};self.errors={};self.latencies=[];self.sequences={}

    async def watch(self,exchange,pair):
        client=self.clients[exchange];key=(exchange,pair);previous=self.sequences.get(key);delay=1
        try:
            while not self.worker.stop.is_set():
                try:
                    raw=await asyncio.wait_for(client.watch_order_book(pair.replace('-','/'),20),timeout=20)
                    received=time.time();feed=self.worker.feeds[exchange]
                    quote=snapshot(exchange,pair,raw,feed.rules[pair],feed.fee,received)
                    if quote.sequence==previous:
                        await asyncio.sleep(.05)
                        continue  # Cached books cannot renew their timestamp.
                    previous=quote.sequence;self.sequences[key]=previous;delay=1
                    if quote.assets[1]!='USDT' and exchange=='bitget':
                        # Bitget's converted minimum needs the fresh conversion used by PublicFeed.book.
                        checked=await asyncio.to_thread(feed.book,pair)
                        quote=Book(exchange,pair,quote.bids,quote.asks,min(quote.timestamp,checked.timestamp),quote.sequence,
                                   quote.fee,quote.step,quote.min_size,checked.min_notional,quote.max_size)
                    if self.queue.full():self.queue.get_nowait()
                    self.queue.put_nowait(quote)
                    self.errors.pop(exchange+':'+pair,None)
                    if raw.get('timestamp') is not None:
                        self.latencies.append(max(0,(received-quote.timestamp)*1000));self.latencies=self.latencies[-500:]
                except asyncio.CancelledError:raise
                except Exception as exc:
                    self.errors[exchange+':'+pair]=type(exc).__name__
                    await asyncio.sleep(delay);delay=min(delay*2,30)
        finally:
            if getattr(client,'has',{}).get('unWatchOrderBook'):
                try:await asyncio.wait_for(client.un_watch_order_book(pair.replace('-','/')),timeout=3)
                except Exception:pass

    async def consume(self):
        while not self.worker.stop.is_set():
            try:quote=await asyncio.wait_for(self.queue.get(),timeout=1)
            except asyncio.TimeoutError:continue
            self.books[quote.exchange,quote.pair]=quote
            now=time.time();fresh=[b for b in self.books.values() if 0<=now-b.timestamp<=self.worker.config['max_age']]
            self.books={(b.exchange,b.pair):b for b in fresh}
            self.worker.universe_status['websocket']={'fresh_books':len(fresh),'queue':self.queue.qsize(),
                'samples':len(self.latencies),'median_event_age_ms':sorted(self.latencies)[len(self.latencies)//2] if self.latencies else None}
            await asyncio.to_thread(self.worker.process_books,fresh,[a+': '+e for a,e in self.errors.items()])

    async def discover(self):
        venue_pairs={}
        for name,feed in self.worker.feeds.items():
            try:
                venue_pairs[name]=await asyncio.to_thread(feed.pairs)
                await self.clients[name].load_markets(reload=True)
                self.errors.pop(name+':discovery',None)
            except Exception as exc:
                venue_pairs[name]=();self.errors[name+':discovery']=type(exc).__name__
        return venue_pairs

    async def run(self):
        consumer=asyncio.create_task(self.consume());tasks=[]
        try:
            venue_pairs=await self.discover();next_discovery=time.monotonic()+900
            batches=plan_batches(venue_pairs,self.worker.config.get('batch_size',12),self.worker.config.get('deny_pairs',[]))
            if not batches:
                await asyncio.to_thread(self.worker.process_books,[],['No supported WebSocket route discovered'])
            self.worker.config['feed_label']='CCXT Pro public WebSocket updates (paper execution)'
            index=0
            while batches and not self.worker.stop.is_set():
                if time.monotonic()>=next_discovery:
                    venue_pairs=await self.discover();next_discovery=time.monotonic()+900
                    batches=plan_batches(venue_pairs,self.worker.config.get('batch_size',12),self.worker.config.get('deny_pairs',[]))
                    if not batches:
                        await asyncio.to_thread(self.worker.process_books,[],['No supported WebSocket route discovered'])
                        break
                pairs=batches[index%len(batches)];index+=1
                self.worker.universe_status.update({'mode':'auto','catalogue_pairs':{n:len(p) for n,p in venue_pairs.items()},
                    'batch_count':len(batches),'batch_number':(index-1)%len(batches)+1,'selected_pairs':pairs,
                    'coverage':'Rotating bounded WebSocket subscriptions'})
                subscriptions={}
                for name in self.clients:
                    required=self.worker.required_pairs(name)
                    missing=[pair for pair in required if pair not in venue_pairs[name]]
                    if missing:self.errors[name+':valuation']='Required valuation market unavailable'
                    else:self.errors.pop(name+':valuation',None)
                    if len(required)>17:
                        self.errors[name+':capacity']='Too many inventory markets for bounded subscriptions'
                        chosen=required[:20]
                    else:
                        self.errors.pop(name+':capacity',None)
                        budget=max(self.worker.config.get('batch_size',12),len(required)+3)
                        capacity=budget-len(required)
                        groups=plan_batches({name:venue_pairs[name]},capacity,self.worker.config.get('deny_pairs',[]))
                        rotating=groups[(index-1)%len(groups)] if groups else ()
                        chosen=tuple(dict.fromkeys((*required,*rotating)))
                    subscriptions[name]=tuple(pair for pair in chosen if pair in venue_pairs[name])
                self.worker.universe_status['active_subscriptions']=subscriptions
                self.worker.universe_status['valuation_priority_pairs']={name:self.worker.required_pairs(name) for name in self.clients}
                tasks=[asyncio.create_task(self.watch(name,pair)) for name,markets in subscriptions.items() for pair in markets]
                end=time.monotonic()+self.rotation
                while not self.worker.stop.is_set() and time.monotonic()<end:
                    await asyncio.sleep(.2)
                    if consumer.done():consumer.result()
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True);tasks=[]
        finally:
            for task in tasks:task.cancel()
            consumer.cancel();await asyncio.gather(*tasks,consumer,return_exceptions=True)
            await asyncio.gather(*(client.close() for client in self.clients.values()),return_exceptions=True)


def run_public(worker):
    import ccxt.pro as ccxt
    clients={name:getattr(ccxt,name)({'enableRateLimit':True,'timeout':8000,'options':{'defaultType':'spot'}}) for name in worker.feeds}
    asyncio.run(WebSocketRunner(worker,clients).run())
