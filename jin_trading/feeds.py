"""Public REST snapshots, with bounded requests and exchange rule validation.

This fallback is polling, not HFT. The Hummingbot bridge can supply WebSocket books.
Fee assumptions are configuration values, not verified account-specific fees.
"""
import json
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from jin_trading.arbitrage import Book, number

HOSTS = {'kucoin': 'https://api.kucoin.com', 'binance': 'https://api.binance.com',
         'bitget': 'https://api.bitget.com'}
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


def fetch_json(url):
    with urlopen(Request(url, headers={'User-Agent': 'JIN-paper-scanner/1.0'}), timeout=15) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
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
        self.next_request, self.blocked_until = 0, 0
        self.request_interval = 0.25

    def get(self, path, **query):
        if time.monotonic() < self.blocked_until:
            raise ValueError('Exchange cooling down after HTTP rejection')
        time.sleep(max(0, self.next_request - time.monotonic()))
        self.next_request = time.monotonic() + self.request_interval
        try:
            value = self.fetch(HOSTS[self.exchange] + path + ('?' + urlencode(query) if query else ''))
        except HTTPError as exc:
            if exc.code in (418, 429, 451):
                try:
                    delay = max(60, min(3600, float(exc.headers.get('Retry-After', '60'))))
                except (ValueError, TypeError):
                    delay = 60
                self.blocked_until = time.monotonic() + delay
            raise
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

    @staticmethod
    def _bitget_quote_usdt_prices(tickers):
        """Return quote-asset values in USDT from one all-spot-tickers snapshot."""
        raw = {}
        for item in tickers:
            symbol = str(item.get('symbol', '')).upper()
            try:
                price = number(item.get('lastPrice'))
            except (ValueError, TypeError, InvalidOperation):
                continue
            if symbol and price > 0:
                raw[symbol] = price
        prices = {'USDT': Decimal('1')}
        assets = set()
        for symbol in raw:
            if symbol.endswith('USDT') and len(symbol) > 4:
                assets.add(symbol[:-4])
            if symbol.startswith('USDT') and len(symbol) > 4:
                assets.add(symbol[4:])
        for asset in assets:
            direct = raw.get(asset + 'USDT')
            inverse = raw.get('USDT' + asset)
            if direct and direct > 0:
                prices[asset] = direct
            elif inverse and inverse > 0:
                prices[asset] = Decimal('1') / inverse
        return prices

    def refresh_rules(self):
        rules = {}
        if self.exchange == 'kucoin':
            for item in self.get('/api/v2/symbols'):
                if not item.get('enableTrading'):
                    continue
                try:
                    step = number(item.get('baseIncrement'))
                    minimum = number(item.get('baseMinSize'))
                    notional = number(item.get('minFunds'))
                    maximum = number(item.get('baseMaxSize'))
                    if step <= 0 or minimum < 0 or notional < 0 or maximum <= 0:
                        raise ValueError('invalid KuCoin trading rule')
                    symbol = str(item.get('symbol', ''))
                    if '-' not in symbol:
                        raise ValueError('invalid KuCoin symbol')
                except (ValueError, TypeError, InvalidOperation):
                    # One malformed/incomplete market must not take down discovery.
                    continue
                rules[symbol] = (step, minimum, notional, maximum)
        elif self.exchange == 'binance':
            for item in self.get('/api/v3/exchangeInfo')['symbols']:
                if (item.get('status') != 'TRADING' or not item.get('isSpotTradingAllowed', True)
                        or 'MARKET' not in item.get('orderTypes', [])):
                    continue
                try:
                    filters = {f['filterType']: f for f in item['filters']}
                    lot = filters['LOT_SIZE']
                    market = filters.get('MARKET_LOT_SIZE', {})
                    step = max(number(lot['stepSize']), number(market.get('stepSize', 0)))
                    minimum = max(number(lot['minQty']), number(market.get('minQty', 0)))
                    maximum = min(number(lot['maxQty']), number(market.get('maxQty', lot['maxQty'])))
                    notional = max(number(filters.get('MIN_NOTIONAL', {}).get('minNotional', 0)),
                                   number(filters.get('NOTIONAL', {}).get('minNotional', 0)))
                    if step <= 0 or minimum < 0 or maximum <= 0 or notional < 0:
                        raise ValueError('invalid Binance trading rule')
                except (KeyError, ValueError, TypeError, InvalidOperation):
                    continue
                rules[f"{item['baseAsset']}-{item['quoteAsset']}"] = (step, minimum, notional, maximum)
        else:
            instruments = self.get('/api/v2/spot/public/symbols')
            tickers = self.get('/api/v3/market/tickers', category='SPOT')
            quote_usdt = self._bitget_quote_usdt_prices(tickers)
            for item in instruments:
                if item.get('status') != 'online':
                    continue
                quote = item['quoteCoin']
                quote_price = quote_usdt.get(quote)
                if not quote_price or quote_price <= 0:
                    continue
                try:
                    min_notional_quote = number(item['minTradeUSDT']) / quote_price
                    step = Decimal(10) ** -int(item['quantityPrecision'])
                    minimum = number(item['minTradeAmount'])
                    maximum = number(item['maxTradeAmount'])
                    if step <= 0 or minimum < 0 or min_notional_quote < 0 or maximum <= 0:
                        raise ValueError('invalid Bitget trading rule')
                except (KeyError, ValueError, TypeError, InvalidOperation):
                    continue
                rules[f"{item['baseCoin']}-{quote}"] = (
                    step, minimum, min_notional_quote, maximum)
        self.rules, self.rules_at = rules, time.time()

    def pairs(self):
        if time.time() - self.rules_at > 900:
            self.refresh_rules()
        return tuple(sorted(self.rules))

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
            stamp, sequence = requested, str(data['lastUpdateId'])
        else:
            data = self.get('/api/v2/spot/market/orderbook', symbol=symbol, type='step0', limit=20)
            stamp, sequence = float(data['ts']) / 1000, str(data['ts'])
        bids = tuple((number(p), number(q)) for p, q, *_ in data['bids'])
        asks = tuple((number(p), number(q)) for p, q, *_ in data['asks'])
        step, minimum, notional, maximum = self.rules[pair]
        return Book(self.exchange, pair, bids, asks, stamp, sequence, self.fee,
                    step, minimum, notional, maximum)
