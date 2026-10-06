"""Public REST snapshots, with bounded requests and exchange rule validation.

This fallback is polling, not HFT. The Hummingbot bridge can supply WebSocket books.
Fee assumptions are configuration values, not verified account-specific fees.
"""
import json
import time
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from jin_trading.arbitrage import Book, number

HOSTS = {'kucoin': 'https://api.kucoin.com', 'binance': 'https://api.binance.com',
         'bitget': 'https://api.bitget.com'}


def fetch_json(url):
    with urlopen(Request(url, headers={'User-Agent': 'JIN-paper-scanner/1.0'}), timeout=8) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Response too large')
    return json.loads(raw)


class PublicFeed:
    def __init__(self, exchange, fee, fetch=fetch_json):
        if exchange not in HOSTS:
            raise ValueError('Unsupported exchange')
        self.exchange, self.fee, self.fetch = exchange, number(fee), fetch
        if not 0 <= self.fee < 1:
            raise ValueError('Invalid fee')
        self.rules, self.rules_at = {}, 0

    def get(self, path, **query):
        value = self.fetch(HOSTS[self.exchange] + path + ('?' + urlencode(query) if query else ''))
        if self.exchange == 'kucoin':
            if value.get('code') != '200000':
                raise ValueError('KuCoin API rejected request')
            return value['data']
        if self.exchange == 'bitget':
            if value.get('code') != '00000':
                raise ValueError('Bitget API rejected request')
            return value['data']
        if 'code' in value:
            raise ValueError('Binance API rejected request')
        return value

    def refresh_rules(self):
        rules = {}
        if self.exchange == 'kucoin':
            for item in self.get('/api/v2/symbols'):
                if item.get('enableTrading'):
                    rules[item['symbol']] = (number(item['baseIncrement']), number(item['baseMinSize']),
                                              number(item['minFunds']), number(item['baseMaxSize']))
        elif self.exchange == 'binance':
            for item in self.get('/api/v3/exchangeInfo')['symbols']:
                if item.get('status') != 'TRADING' or 'MARKET' not in item.get('orderTypes', []):
                    continue
                filters = {f['filterType']: f for f in item['filters']}
                lot = filters['LOT_SIZE']
                market = filters.get('MARKET_LOT_SIZE', {})
                step = max(number(lot['stepSize']), number(market.get('stepSize', 0)))
                minimum = max(number(lot['minQty']), number(market.get('minQty', 0)))
                maximum = min(number(lot['maxQty']), number(market.get('maxQty', lot['maxQty'])))
                notional = max(number(filters.get('MIN_NOTIONAL', {}).get('minNotional', 0)),
                               number(filters.get('NOTIONAL', {}).get('minNotional', 0)))
                rules[f"{item['baseAsset']}-{item['quoteAsset']}"] = (step, minimum, notional, maximum)
        else:
            for item in self.get('/api/v2/spot/public/symbols'):
                # minTradeUSDT cannot be treated as a BTC-denominated minimum.
                if item.get('status') == 'online' and item['quoteCoin'] == 'USDT':
                    rules[f"{item['baseCoin']}-{item['quoteCoin']}"] = (
                        Decimal(10) ** -int(item['quantityPrecision']), number(item['minTradeAmount']),
                        number(item['minTradeUSDT']), number(item['maxTradeAmount']))
        self.rules, self.rules_at = rules, time.time()

    def book(self, pair):
        if time.time() - self.rules_at > 900:
            self.refresh_rules()
        if pair not in self.rules:
            raise ValueError(f'{pair}: inactive, unsupported, or missing trading rules')
        symbol = pair if self.exchange == 'kucoin' else pair.replace('-', '')
        requested = time.time()
        if self.exchange == 'kucoin':
            data = self.get('/api/v1/market/orderbook/level2_20', symbol=symbol)
            stamp = float(data['time']) / 1000
            sequence = str(data['sequence'])
        elif self.exchange == 'binance':
            data = self.get('/api/v3/depth', symbol=symbol, limit=20)
            # REST response has no event timestamp. Request-start time is a conservative local age.
            stamp, sequence = requested, str(data['lastUpdateId'])
        else:
            data = self.get('/api/v2/spot/market/orderbook', symbol=symbol, type='step0', limit=20)
            stamp, sequence = float(data['ts']) / 1000, str(data['ts'])
        bids = tuple((number(p), number(q)) for p, q, *_ in data['bids'])
        asks = tuple((number(p), number(q)) for p, q, *_ in data['asks'])
        step, minimum, notional, maximum = self.rules[pair]
        return Book(self.exchange, pair, bids, asks, stamp, sequence, self.fee,
                    step, minimum, notional, maximum)
