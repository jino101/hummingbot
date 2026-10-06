import json
import tempfile
import time
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from jin_trading.feeds import PublicFeed
from jin_trading.store import Store
from jin_trading.worker import Worker, load_config
from test_arbitrage import triangle


class FeedTests(unittest.TestCase):
    def test_kucoin_parse(self):
        now=int(time.time()*1000)
        def fetch(url):
            data=([{'symbol':'A-USDT','enableTrading':True,'baseIncrement':'0.01','baseMinSize':'0.1','minFunds':'1','baseMaxSize':'1000'}]
                  if '/symbols' in url else {'time':now,'sequence':'42','bids':[['1','100']],'asks':[['1.01','100']]})
            return {'code':'200000','data':data}
        feed=PublicFeed('kucoin','0.002',fetch)
        book=feed.book('A-USDT')
        self.assertEqual(book.sequence,'42')
        self.assertEqual(book.min_notional,D('1'))
        with self.assertRaises(ValueError):feed.book('B-USDT')

    def test_binance_parse_and_market_limits(self):
        def fetch(url):
            if 'exchangeInfo' in url:return {'symbols':[{'status':'TRADING','orderTypes':['MARKET'], 'baseAsset':'A','quoteAsset':'USDT','filters':[
                {'filterType':'LOT_SIZE','minQty':'0.01','maxQty':'1000','stepSize':'0.01'},
                {'filterType':'MARKET_LOT_SIZE','minQty':'0.1','maxQty':'100','stepSize':'0'},
                {'filterType':'NOTIONAL','minNotional':'5'}]}]}
            return {'lastUpdateId':123,'bids':[['1','100']],'asks':[['1.01','100']]}
        book=PublicFeed('binance','0.001',fetch).book('A-USDT')
        self.assertEqual(book.min_size,D('0.1'))
        self.assertEqual(book.max_size,D('100'))
        self.assertEqual(book.min_notional,D('5'))

    def test_bitget_parse_and_non_usdt_quote_conversion(self):
        now=str(int(time.time()*1000))
        def fetch(url):
            if '/api/v2/spot/public/symbols' in url:
                data=[
                    {'symbol':'AUSDT','baseCoin':'A','quoteCoin':'USDT','status':'online','quantityPrecision':'2','minTradeAmount':'0.01','minTradeUSDT':'1','maxTradeAmount':'1000'},
                    {'symbol':'ABTC','baseCoin':'A','quoteCoin':'BTC','status':'online','quantityPrecision':'3','minTradeAmount':'0.001','minTradeUSDT':'5','maxTradeAmount':'100'}
                ]
            elif '/api/v3/market/tickers' in url:
                data=[{'symbol':'BTCUSDT','lastPrice':'50000'}]
            else:
                data={'ts':now,'bids':[['0.001','100']],'asks':[['0.0011','100']]}
            return {'code':'00000','data':data}
        feed=PublicFeed('bitget','0.002',fetch)
        usdt=feed.book('A-USDT')
        btc=feed.book('A-BTC')
        self.assertEqual(usdt.step,D('0.01'))
        self.assertEqual(btc.step,D('0.001'))
        self.assertEqual(btc.min_notional,D('0.0001'))

    def test_bitget_non_usdt_without_conversion_fails_closed(self):
        def fetch(url):
            if '/api/v2/spot/public/symbols' in url:
                data=[{'symbol':'AABC','baseCoin':'A','quoteCoin':'ABC','status':'online','quantityPrecision':'2','minTradeAmount':'0.01','minTradeUSDT':'1','maxTradeAmount':'1000'}]
            elif '/api/v3/market/tickers' in url:
                data=[]
            else:
                data={'ts':str(int(time.time()*1000)),'bids':[['1','100']],'asks':[['1.01','100']]}
            return {'code':'00000','data':data}
        feed=PublicFeed('bitget','0.002',fetch)
        self.assertEqual(feed.pairs(),())
        with self.assertRaises(ValueError):feed.book('A-ABC')

    def test_api_errors(self):
        for ex,code in [('kucoin','400000'),('bitget','40000'),('binance',-1)]:
            feed=PublicFeed(ex,'0.001',lambda url:{'code':code})
            with self.assertRaises(ValueError):feed.refresh_rules()
        with self.assertRaises(ValueError):PublicFeed('unknown','0.01')
        with self.assertRaises(ValueError):PublicFeed('kucoin','2')


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'paper.sqlite')
        self.config=load_config('jin_trading/config.example.json')
        self.config['pair_mode']='manual'
        self.store.configure({bot:spec['budget'] for bot,spec in self.config['bots'].items()})
        self.worker=Worker(self.store,self.config)

    def tearDown(self):self.tmp.cleanup()

    def test_real_processing_paper_and_dedup(self):
        self.store.control('kucoin-triangle',True)
        self.worker.process_books(triangle(),[])
        first=self.store.snapshot()
        self.assertEqual(len(first['trades']),1)
        self.assertGreater(D(first['capital']),D('5'))
        self.worker.process_books(triangle(),[])
        self.assertEqual(len(self.store.snapshot()['trades']),1)

    def test_feed_failure_is_visible_and_does_not_trade(self):
        self.store.control('kucoin-triangle',True)
        for feed in self.worker.feeds.values():feed.book=lambda pair: (_ for _ in ()).throw(ValueError('offline'))
        self.worker.tick()
        state=self.store.snapshot()
        self.assertEqual(len(state['trades']),0)
        self.assertEqual(len(state['bots'][0]['status']['errors']),3)

    def test_config_rejects_live_and_unbounded_risk(self):
        for key,value in [('mode','live'),('poll_seconds',0),('slippage','0'),('min_profit','-1'),('max_age',0),('pairs',[]),('stress_fraction','0'),('max_deploy_fraction','1')]:
            config=dict(self.config);config[key]=value
            path=Path(self.tmp.name)/'bad.json';path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):load_config(path)
