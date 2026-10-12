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


async def thread_call(function, *args):
    """Cancellation must not abandon a thread still holding worker resources.

    Cancelling to_thread's awaiter cannot stop its underlying synchronous work.
    Drain that work before propagating cancellation, including repeated cancels
    from nested runner cleanup, so run() cannot return with SQLite still open.
    """
    operation = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while not operation.done():
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            if not cancelled:
                raise
    if cancelled:
        # Retrieve an exception raised during shutdown without replacing the
        # caller's cancellation or leaking an unhandled-task warning.
        if not operation.cancelled():
            operation.exception()
        raise asyncio.CancelledError
    return operation.result()


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
        self.pending_books={}
        self.clock=time.monotonic

    async def publish_book(self, quote):
        """Keep the latest update per market; a busy market cannot evict another leg."""
        key=(quote.exchange,quote.pair)
        queued=key in self.pending_books
        self.pending_books[key]=quote
        if not queued:
            await self.queue.put(('book',key))

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
                        checked=await thread_call(feed.book,pair)
                        quote=Book(exchange,pair,quote.bids,quote.asks,min(quote.timestamp,checked.timestamp),quote.sequence,
                                   quote.fee,quote.step,quote.min_size,checked.min_notional,quote.max_size)
                    await self.publish_book(quote)
                    self.errors.pop(exchange+':'+pair,None)
                    if raw.get('timestamp') is not None:
                        self.latencies.append((received-quote.timestamp)*1000);self.latencies=self.latencies[-500:]
                except asyncio.CancelledError:raise
                except Exception as exc:
                    self.errors[exchange+':'+pair]=type(exc).__name__
                    await asyncio.sleep(delay);delay=min(delay*2,30)
        finally:
            self.errors.pop(exchange+':'+pair,None)
            if getattr(client,'has',{}).get('unWatchOrderBook'):
                try:await asyncio.wait_for(client.un_watch_order_book(pair.replace('-','/')),timeout=3)
                except Exception:pass

    async def consume(self):
        while not self.worker.stop.is_set():
            try:item=await asyncio.wait_for(self.queue.get(),timeout=1)
            except asyncio.TimeoutError:
                # A disconnected or silent feed must still publish its errors
                # and expire old books without renewing their timestamps.
                pending=[]
            else:pending=[item]
            while not self.queue.empty():pending.append(self.queue.get_nowait())
            notices=[];received={}
            for kind,value in pending:
                if kind=='status':
                    notices.append(value)
                else:
                    quote=self.pending_books.pop(value,None)
                    if quote is not None:
                        self.books[value]=quote
                        received[quote.exchange]=received.get(quote.exchange,0)+1
            now=time.time();future=[b for b in self.books.values() if b.timestamp>now]
            fresh=[b for b in self.books.values() if 0<=now-b.timestamp<=self.worker.config['max_age']]
            self.books={(b.exchange,b.pair):b for b in fresh}
            self.worker.universe_status['websocket']={'fresh_books':len(fresh),'queue':self.queue.qsize(),
                'samples':len(self.latencies),'median_event_age_ms':sorted(self.latencies)[len(self.latencies)//2] if self.latencies else None}
            for name, row in list(self.worker.universe_status.get('venues', {}).items()):
                status = dict(row, fresh_books=sum(b.exchange == name for b in fresh),
                              future_books=sum(b.exchange == name for b in future),
                              max_future_seconds=max((b.timestamp-now for b in future if b.exchange==name),default=0))
                status['books_received'] = status.get('books_received', 0) + received.get(name,0)
                self.publish_venue(name, status)
            errors=notices+[a+': '+e for a,e in self.errors.items()]
            await thread_call(self.worker.process_books,fresh,errors)

    async def discover(self, names=None):
        async def venue(name):
            feed = self.worker.feeds[name]
            try:
                pairs=await thread_call(feed.pairs)
                await asyncio.wait_for(self.clients[name].load_markets(reload=True), timeout=20)
                self.errors.pop(name+':discovery',None)
                return name, pairs
            except Exception as exc:
                self.errors[name+':discovery']=type(exc).__name__
                return name, ()
        return dict(await asyncio.gather(*(venue(name) for name in (names or self.worker.feeds))))

    async def pause(self, seconds, consumer):
        """Wait with bounded shutdown latency and surface consumer failures."""
        end = self.clock() + seconds
        while not self.worker.stop.is_set() and self.clock() < end:
            if consumer.done():
                consumer.result()
                raise RuntimeError('WebSocket consumer stopped unexpectedly')
            await asyncio.sleep(min(.2, max(0, end - self.clock())))

    def publish_venue(self, name, status):
        self.worker.publish_venue_status(name, status)
        venues = self.worker.universe_status['venues']
        subscriptions = {name: row.get('active_subscriptions', ()) for name, row in venues.items()
                         if row.get('active_subscriptions')}
        self.worker.universe_status.update(active_subscriptions=subscriptions,
            discovery_errors=dict(self.errors), coverage='Independent bounded WebSocket subscriptions per exchange')
        retries = [row['discovery_retry_seconds'] for row in venues.values() if 'discovery_retry_seconds' in row]
        if retries and not subscriptions:
            self.worker.universe_status['discovery_retry_seconds'] = min(retries)
        else:
            self.worker.universe_status.pop('discovery_retry_seconds', None)

    async def run_venue(self, name, consumer):
        tasks={};next_discovery=0;retry_delay=1;pairs=()
        try:
            while not self.worker.stop.is_set():
                if self.clock()>=next_discovery:
                    pairs=(await self.discover((name,)))[name]
                    next_discovery=self.clock()+900 if pairs else 0
                status=self.worker.select_venue_batch(name,pairs)
                status['active_subscriptions']=status['selected_pairs']
                removed=[tasks.pop(pair) for pair in list(tasks) if pair not in status['selected_pairs']]
                for task in removed:task.cancel()
                await asyncio.gather(*removed,return_exceptions=True)
                if status['missing_required_pairs']:
                    self.errors[name+':valuation']='Required valuation market unavailable'
                else:self.errors.pop(name+':valuation',None)
                if status['capacity_exhausted']:
                    self.errors[name+':capacity']='Too many inventory markets for bounded subscriptions'
                else:self.errors.pop(name+':capacity',None)
                if not status['selected_pairs']:
                    status.update(state='discovery_failed' if name+':discovery' in self.errors else 'empty',
                        discovery_retry_seconds=retry_delay, error=self.errors.get(name+':discovery'))
                    self.publish_venue(name,status)
                    # Only the consumer calls process_books, including empty-feed status.
                    await self.queue.put(('status', 'No supported WebSocket route discovered: '+name))
                    await self.pause(retry_delay,consumer)
                    retry_delay=min(retry_delay*2,30);next_discovery=0
                    continue
                retry_delay=1
                status['state']='subscribed'
                self.publish_venue(name,status)
                for pair in status['selected_pairs']:
                    if pair not in tasks:
                        tasks[pair]=asyncio.create_task(self.watch(name,pair))
                await self.pause(self.rotation,consumer)
        finally:
            for task in tasks.values():task.cancel()
            await asyncio.gather(*tasks.values(),return_exceptions=True)

    async def run(self):
        self.worker.config['feed_label']='CCXT Pro public WebSocket updates (paper execution)'
        self.worker.universe_status['mode']='auto'
        consumer=asyncio.create_task(self.consume())
        venues=[asyncio.create_task(self.run_venue(name,consumer)) for name in self.clients]
        try:
            await asyncio.gather(*venues)
        finally:
            for task in venues:task.cancel()
            consumer.cancel();await asyncio.gather(*venues,consumer,return_exceptions=True)
            await asyncio.gather(*(client.close() for client in self.clients.values()),return_exceptions=True)


def run_public(worker):
    import ccxt.pro as ccxt
    clients={name:getattr(ccxt,name)({'enableRateLimit':True,'timeout':8000,'options':{'defaultType':'spot'}}) for name in worker.feeds}
    asyncio.run(WebSocketRunner(worker,clients).run())

