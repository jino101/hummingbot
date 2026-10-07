"""Sequential IOC execution with durable intent and explicit reconciliation.

Broker methods are injected. Tests use paper brokers; real adapters require a
separately configured live portfolio and current verified permissions.
"""
import json
import time
from decimal import Decimal, ROUND_DOWN

from jin_trading.arbitrage import number
from jin_trading.supervisor import TERMINAL


def order_size(book, source, amount, slippage=Decimal('.001')):
    amount=number(amount)/(1+book.fee)
    target,estimate=book.convert(source,amount,slippage)
    base,quote=book.assets
    if source==quote:
        side='buy';quantity=((estimate/(1-book.fee))/book.step).to_integral_value(rounding=ROUND_DOWN)*book.step;depth=book.asks
    else:
        side='sell';quantity=(amount/book.step).to_integral_value(rounding=ROUND_DOWN)*book.step;depth=book.bids
    remaining=quantity;worst=None
    for price,size in depth:
        remaining-=min(remaining,size);worst=price
        if remaining==0:break
    if remaining or worst is None:raise ValueError('Insufficient executable depth')
    limit=worst*(1+slippage if side=='buy' else 1-slippage)
    if quantity*limit<book.min_notional or quantity<book.min_size:raise ValueError('Order below exchange minimum')
    return side,quantity,limit,target


class ExecutionEngine:
    def __init__(self, portfolio, brokers, max_age=3, slippage=Decimal('.001')):
        self.portfolio,self.brokers=portfolio,brokers
        self.max_age,self.slippage=max_age,number(slippage)

    def submit(self, run, account, pair, side, quantity, price):
        broker=self.brokers[account]
        if bool(getattr(broker,'is_live',False)) != (self.portfolio.mode=='live'):
            raise ValueError('Broker/portfolio live mode mismatch')
        client=self.portfolio.prepare(run,account,pair,side,quantity,price)
        self.portfolio.submitting(client)
        try:
            order=broker.submit(client,pair,side,quantity,price)
            self.portfolio.observe(client,order)
        except Exception as exc:
            self.portfolio.unknown(client, 'Uncertain order submission: '+type(exc).__name__)
            raise ValueError('Submission unconfirmed; reconcile without resubmitting') from exc
        return client,order

    def triangle(self, bot, account, pairs, amount, run_id=None):
        if len(pairs)!=3 or len(set(pairs))!=3:raise ValueError('Three distinct markets required')
        amount=number(amount);source='USDT'
        run=self.portfolio.reserve(bot,[(account,source,amount,amount)],run_id)
        current=amount
        try:
            for pair in pairs:
                book=self.brokers[account].book(pair)
                if not 0<=time.time()-book.timestamp<=self.max_age:raise ValueError('Stale order book')
                side,quantity,price,target=order_size(book,source,current,self.slippage)
                client,order=self.submit(run,account,pair,side,quantity,price)
                if order['status'] not in TERMINAL or number(order.get('filled',0))!=quantity:
                    raise ValueError('Partial or pending leg; no subsequent order allowed')
                current=number(order['filled'] if side=='buy' else order['cost'])
                fees=order.get('fees')
                if fees is None:fees=[order['fee']] if order.get('fee') else []
                for fee in fees:
                    if fee['currency']==target:current-=number(fee['cost'])
                if current<=0:raise ValueError('Fees consumed received asset')
                source=target
            if source!='USDT':raise ValueError('Route did not return to USDT')
            self.portfolio.finish(run,True)
            return {'run':run,'input':str(amount),'output':str(current),'profit':str(current-amount)}
        except Exception as exc:
            if not self.portfolio.abort_unsubmitted(run):
                self.portfolio.finish(run,False,type(exc).__name__+': '+str(exc))
            raise

    def cross(self, bot, buy_account, sell_account, pair, quantity, run_id=None):
        """Prefunded cross-exchange arbitrage. No automatic transfers.

        Buy quote and sell base are reserved together. The two IOC orders are
        journalled separately; a partial/uncertain first leg stops the second.
        """
        quantity=number(quantity)
        if buy_account==sell_account or quantity<=0:raise ValueError('Two accounts and positive quantity required')
        buy=self.brokers[buy_account].book(pair);sell=self.brokers[sell_account].book(pair)
        if buy.assets!=sell.assets or buy.assets[1]!='USDT':raise ValueError('USDT market required')
        for book in (buy,sell):
            if not 0<=time.time()-book.timestamp<=self.max_age:raise ValueError('Stale order book')
            if quantity/book.step!=(quantity/book.step).to_integral_value():raise ValueError('Invalid quantity precision')
        buy_price=buy.asks[0][0]*(1+self.slippage);sell_price=sell.bids[0][0]*(1-self.slippage)
        cost=quantity*buy_price*(1+buy.fee);value=quantity*sell.bids[0][0]
        if cost<buy.min_notional or quantity*sell_price<sell.min_notional:raise ValueError('Exchange minimum not met')
        run=self.portfolio.reserve(bot,[(buy_account,'USDT',cost,cost),(sell_account,sell.assets[0],quantity,value)],run_id)
        try:
            orders=[]
            for account,side,price in ((buy_account,'buy',buy_price),(sell_account,'sell',sell_price)):
                book=self.brokers[account].book(pair)
                if not 0<=time.time()-book.timestamp<=self.max_age:raise ValueError('Stale cross-exchange leg')
                _,order=self.submit(run,account,pair,side,quantity,price)
                orders.append(order)
                if order['status'] not in TERMINAL or number(order.get('filled',0))!=quantity:
                    raise ValueError('Partial or pending cross-exchange leg')
                fees=order.get('fees') or ([order['fee']] if order.get('fee') else [])
                if any(f['currency']==buy.assets[0] and number(f['cost'])>0 for f in fees):
                    raise ValueError('Base-denominated fee requires explicit inventory reconciliation')
            self.portfolio.finish(run,True)
            return {'run':run,'orders':orders,'inventory_rebalance_required':True}
        except Exception as exc:
            if not self.portfolio.abort_unsubmitted(run):self.portfolio.finish(run,False,str(exc))
            raise

    def stop_bot(self, bot):
        with self.portfolio.db() as db:
            runs=[r[0] for r in db.execute("SELECT id FROM portfolio_runs WHERE bot=? AND state='running'",(bot,))]
        for run in runs:
            if not self.portfolio.abort_unsubmitted(run):self.portfolio.finish(run,False,'Bot stopped during execution')
        if runs:return self.stop_all()
        return []

    def directional(self, bot, account, pair, side, quantity):
        if self.portfolio.mode!='paper':raise ValueError('Directional strategies are paper-only')
        book=self.brokers[account].book(pair);quantity=number(quantity)
        if not 0<=time.time()-book.timestamp<=self.max_age:raise ValueError('Stale strategy book')
        base,quote=book.assets
        if quote!='USDT' or side not in ('buy','sell'):raise ValueError('USDT spot strategy required')
        price=(book.asks[0][0]*(1+self.slippage) if side=='buy' else book.bids[0][0]*(1-self.slippage))
        amount=quantity*price*(1+book.fee) if side=='buy' else quantity
        value=quantity*price*(1+book.fee)
        if quantity<book.min_size or quantity>book.max_size or quantity*price<book.min_notional:
            raise ValueError('Strategy order outside market limits')
        run=self.portfolio.reserve(bot,[(account,quote if side=='buy' else base,amount,value)])
        try:
            _,order=self.submit(run,account,pair,side,quantity,price)
            if order['status'] not in TERMINAL or number(order['filled'])!=quantity:raise ValueError('Strategy order incomplete')
            self.portfolio.finish(run,True)
            return {'run':run,'order':order}
        except Exception as exc:
            if not self.portfolio.abort_unsubmitted(run):self.portfolio.finish(run,False,str(exc))
            raise

    def reconcile(self):
        """Read by exchange/client ID, including terminal orders on held runs.

        A late fill is retained. Neither a successful cancel request nor absence
        from one fetched page is treated as proof that an order never existed.
        """
        results=[]
        for row in self.portfolio.orders(True):
            try:
                order=self.brokers[row['account']].lookup(row['exchange_id'],row['client_id'],row['pair'])
                if order is None:raise ValueError('Exchange has not confirmed order state')
                self.portfolio.observe(row['client_id'],order)
                results.append({'client_id':row['client_id'],'status':order['status']})
            except Exception as exc:
                results.append({'client_id':row['client_id'],'status':'unknown','error':type(exc).__name__})
        return results

    def stop_all(self):
        self.portfolio.halt()
        for row in self.portfolio.orders(True):
            if row['state'] not in TERMINAL:
                try:
                    if row['exchange_id']:
                        self.brokers[row['account']].cancel(row['exchange_id'],row['pair'])
                except Exception:
                    pass  # The journal remains unsettled; reconciliation exposes the failure.
        return self.reconcile()


class PaperBroker:
    is_live=False
    def __init__(self, portfolio, account, books, initial='5'):
        self.portfolio,self.account,self.books=portfolio,account,books
        with portfolio.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS paper_wallets (account TEXT, asset TEXT, amount TEXT, PRIMARY KEY(account,asset))')
            db.execute('CREATE TABLE IF NOT EXISTS paper_orders (client TEXT PRIMARY KEY, response TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS paper_positions (account TEXT,asset TEXT,entry TEXT,PRIMARY KEY(account,asset))')
            db.execute('INSERT OR IGNORE INTO paper_wallets VALUES (?,?,?)',(account,'USDT',str(initial)))

    def book(self,pair):return self.books[pair]

    def submit(self,client,pair,side,quantity,price):
        book=self.book(pair);base,quote=book.assets
        with self.portfolio.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM paper_orders WHERE client=?',(client,)).fetchone():raise ValueError('Duplicate client identifier')
            remaining=quantity;filled=Decimal('0');cost=Decimal('0')
            for level,size in (book.asks if side=='buy' else book.bids):
                if (side=='buy' and level>price) or (side=='sell' and level<price):break
                used=min(remaining,size);filled+=used;cost+=used*level;remaining-=used
                if remaining==0:break
            fee=cost*book.fee;deltas={base:filled if side=='buy' else -filled,quote:-cost-fee if side=='buy' else cost-fee}
            before=db.execute('SELECT amount FROM paper_wallets WHERE account=? AND asset=?',(self.account,base)).fetchone()
            held=number(before[0] if before else 0)
            previous=db.execute('SELECT entry FROM paper_positions WHERE account=? AND asset=?',(self.account,base)).fetchone()
            if side=='buy' and filled:
                entry=(held*number(previous[0] if previous else 0)+cost+fee)/(held+filled)
                db.execute('INSERT OR REPLACE INTO paper_positions VALUES (?,?,?)',(self.account,base,str(entry)))
            elif side=='sell' and held==filled:
                db.execute('DELETE FROM paper_positions WHERE account=? AND asset=?',(self.account,base))
            for asset,delta in deltas.items():
                row=db.execute('SELECT amount FROM paper_wallets WHERE account=? AND asset=?',(self.account,asset)).fetchone()
                total=number(row[0] if row else 0)+delta
                if total<0:raise ValueError('Paper inventory insufficient')
                db.execute('INSERT OR REPLACE INTO paper_wallets VALUES (?,?,?)',(self.account,asset,str(total)))
            response={'id':client,'status':'closed' if not remaining else 'canceled','filled':str(filled),'cost':str(cost),
                      'fees':[{'currency':quote,'cost':str(fee)}]}
            db.execute('INSERT INTO paper_orders VALUES (?,?)',(client,json.dumps(response)))
        return response

    def lookup(self,exchange_id,client,pair):
        with self.portfolio.db() as db:
            row=db.execute('SELECT response FROM paper_orders WHERE client=?',(client,)).fetchone()
            return json.loads(row[0]) if row else None

    def cancel(self,exchange_id,pair):return self.lookup(exchange_id,exchange_id,pair)

    def balances(self):
        with self.portfolio.db() as db:
            return {r[0]:number(r[1]) for r in db.execute('SELECT asset,amount FROM paper_wallets WHERE account=?',(self.account,))}

    def entry_prices(self):
        with self.portfolio.db() as db:
            return {r[0]:number(r[1]) for r in db.execute('SELECT asset,entry FROM paper_positions WHERE account=?',(self.account,))}

    def sync(self):
        wallet=self.balances();prices={'USDT':Decimal('1')}
        for book in self.books.values():
            if book.assets[1]=='USDT' and 0<=time.time()-book.timestamp<=3:
                prices[book.assets[0]]=book.bids[0][0]
        if any(v and a not in prices for a,v in wallet.items()):raise ValueError('Fresh inventory valuation missing')
        equity=sum((v*prices.get(a,0) for a,v in wallet.items()),Decimal('0'))
        self.portfolio.update_account(self.account,equity,wallet)
        return equity
