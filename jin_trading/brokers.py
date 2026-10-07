"""Optional CCXT spot adapter and fixed-host stock/forex demo transports.

No credentials are stored in this module. Runtime credentials come from the
operator's environment. Importing it performs no network or trading action.
"""
import json
import time
from dataclasses import replace
from decimal import Decimal
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from jin_trading.arbitrage import number


class SpotBroker:
    mode='live'
    is_live=True
    def __init__(self, client, feed, armed=False):
        if client.id not in ('binance','kucoin','bitget') or feed.exchange!=client.id:
            raise ValueError('Unsupported or mismatched spot account')
        self.client,self.feed,self.armed=client,feed,armed
        self.verified_fees={}

    def book(self,pair):
        verified=self.verified_fees.get(pair)
        if self.armed and (not verified or not 0<=time.time()-verified[0]<=120):
            raise ValueError('Fresh verified account fee required')
        book=self.feed.book(pair)
        return replace(book,fee=verified[1]) if verified else book

    def submit(self,client_id,pair,side,quantity,price):
        if not self.armed:raise ValueError('Live adapter is not armed')
        symbol=pair.replace('-','/')
        amount=self.client.amount_to_precision(symbol,float(quantity))
        limit=self.client.price_to_precision(symbol,float(price))
        if number(amount)!=quantity:raise ValueError('Precision changed planned quantity')
        # Rounding the limit may narrow execution, never widen the reserved cost.
        if side=='buy' and number(limit)>price or side=='sell' and number(limit)<price:
            raise ValueError('Precision would widen the order limit')
        order=self.client.create_order(symbol,'limit',side,float(amount),float(limit),
                                       {'timeInForce':'IOC','clientOrderId':client_id})
        return self._fees(order,symbol)

    def _fees(self,order,symbol):
        if number(order.get('filled') or 0)>0 and not (order.get('fees') or order.get('fee')):
            trades=self.client.fetch_my_trades(symbol,limit=100)
            matched=[t for t in trades if str(t.get('order'))==str(order.get('id'))]
            if sum((number(t.get('amount') or 0) for t in matched),Decimal('0'))!=number(order['filled']):
                raise ValueError('Trade page does not confirm every fill')
            fees=[]
            for trade in matched:
                current=trade.get('fees') or ([trade['fee']] if trade.get('fee') else [])
                if not current:raise ValueError('Fill fees not confirmed')
                fees.extend(current)
            order=dict(order,fees=fees)
        return order

    def lookup(self,exchange_id,client_id,pair):
        symbol=pair.replace('-','/')
        if exchange_id:return self._fees(self.client.fetch_order(exchange_id,symbol),symbol)
        # Missing from a fetched page is uncertainty, never proof of absence.
        orders=[]
        for method in ('fetch_open_orders','fetch_closed_orders'):
            if self.client.has.get(''.join([method.split('_')[0]]+[s.title() for s in method.split('_')[1:]])):
                orders.extend(getattr(self.client,method)(symbol,limit=100))
        found=[o for o in orders if o.get('clientOrderId')==client_id]
        if len(found)>1:raise ValueError('Client identifier is not unique')
        return self._fees(found[0],symbol) if found else None

    def cancel(self,exchange_id,pair):return self.client.cancel_order(exchange_id,pair.replace('-','/'))

    def permissions(self):
        started=time.time()
        if self.client.id=='binance':
            raw=self.client.request('account/apiRestrictions','sapi','GET')
            result={'read':raw.get('enableReading'),'trade':raw.get('enableSpotAndMarginTrading'),
                    'withdraw':raw.get('enableWithdrawals')}
        elif self.client.id=='kucoin':
            raw=self.client.request('user/api-key','private','GET')
            data=raw.get('data',{})
            value=data.get('permission')
            if value is None:return {'checked_at':started}
            permissions={str(v).strip().lower() for v in (value if isinstance(value,list) else str(value).split(','))}
            result={'read':'general' in permissions,'trade':bool(permissions & {'spot','unified'}),
                    'withdraw':bool(permissions & {'withdraw','withdrawal','transfer'})}
        else:
            raw=self.client.request('v3/account/info',['private','uta'],'GET')
            data=raw.get('data',{});permissions=data.get('permissions')
            if not isinstance(permissions,list):return {'checked_at':started}
            result={'read':True,'trade':'uta_trade' in permissions and data.get('permType')=='read-and-write',
                    'withdraw':bool(set(permissions)&{'withdraw','transfer','uta_mgt'})}
        return dict(result,checked_at=started)

    def sync(self,portfolio,account):
        started=time.time();balance=self.client.fetch_balance({'type':'spot'})
        free={a:number(v) for a,v in balance.get('free',{}).items() if v is not None}
        total={a:number(v) for a,v in balance.get('total',{}).items() if v is not None and number(v)>0}
        if any(number(v)<0 for v in balance.get('total',{}).values() if v is not None):
            raise ValueError('Negative account inventory is unsupported')
        if any(number(v)>0 for v in balance.get('debt',{}).values() if v is not None):
            raise ValueError('Leveraged account debt is unsupported')
        equity=Decimal('0')
        for asset,amount in total.items():
            if asset=='USDT':equity+=amount
            else:
                book=self.feed.book(asset+'-USDT')
                if not 0<=time.time()-book.timestamp<=3:raise ValueError('Fresh held-asset price required')
                equity+=amount*book.bids[0][0]
        permissions=self.permissions()
        portfolio.update_account(account,equity,free,started,permissions)
        return {'equity':str(equity),'free':{a:str(v) for a,v in free.items()},'permissions':permissions}


def http_json(host,path,method,headers,body=None):
    encoded=None if body is None else json.dumps(body,allow_nan=False).encode()
    request=Request(host+path,method=method,headers=dict(headers,**{'Content-Type':'application/json'}),data=encoded)
    # Demo endpoints are fixed; never follow a redirect with credentials.
    from urllib.request import HTTPRedirectHandler,build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args):raise ValueError('Broker redirect rejected')
    with build_opener(NoRedirect).open(request,timeout=8) as response:
        raw=response.read(4_000_001)
    if len(raw)>4_000_000:raise ValueError('Broker response too large')
    return json.loads(raw) if raw else {}


class AlpacaDemo:
    host='https://paper-api.alpaca.markets'
    mode='demo';is_live=False
    def __init__(self,key,secret,transport=http_json):
        if not key or not secret:raise ValueError('Alpaca demo credentials required')
        self.headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret};self.transport=transport
    def call(self,path,method='GET',body=None):return self.transport(self.host,path,method,self.headers,body)
    def account(self):return self.call('/v2/account')
    def submit(self,client_id,symbol,side,quantity,price):
        if side not in ('buy','sell') or number(quantity)<=0 or number(price)<=0:raise ValueError('Invalid stock order')
        return self.call('/v2/orders','POST',{'symbol':symbol,'qty':str(quantity),'side':side,'type':'limit',
                                           'limit_price':str(price),'time_in_force':'day','client_order_id':client_id})
    def lookup(self,exchange_id,client_id,symbol):
        return self.call('/v2/orders/'+quote(str(exchange_id),safe='') if exchange_id else
                         '/v2/orders:by_client_order_id?'+urlencode({'client_order_id':client_id}))
    def cancel(self,exchange_id,symbol):return self.call('/v2/orders/'+quote(str(exchange_id),safe=''),'DELETE')


class OandaDemo:
    host='https://api-fxpractice.oanda.com'
    mode='demo';is_live=False
    def __init__(self,token,account,transport=http_json):
        if not token or not account:raise ValueError('OANDA practice credentials required')
        self.headers={'Authorization':'Bearer '+token};self.account_id=quote(account,safe='');self.transport=transport
    def call(self,path,method='GET',body=None):return self.transport(self.host,'/v3/accounts/'+self.account_id+path,method,self.headers,body)
    def account(self):return self.call('/summary')
    def submit(self,client_id,pair,side,quantity,price):
        if side not in ('buy','sell') or number(quantity)<=0 or number(price)<=0:raise ValueError('Invalid forex order')
        # MARKET/FOK with a required price bound; no unrestricted market order.
        return self.call('/orders','POST',{'order':{'type':'MARKET','instrument':pair.replace('-','_'),
                          'units':str(number(quantity)*(1 if side=='buy' else -1)),'priceBound':str(price),'timeInForce':'FOK',
                          'positionFill':'DEFAULT','clientExtensions':{'id':client_id}}})
    def lookup(self,exchange_id,client_id,pair):return self.call('/orders/'+quote(str(exchange_id or '@'+client_id),safe=''))
    def cancel(self,exchange_id,pair):return self.call('/orders/'+quote(str(exchange_id),safe='')+'/cancel','PUT')
