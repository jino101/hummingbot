import tempfile
import time
import unittest
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from jin_trading.account_check import check
from jin_trading.brokers import SpotBroker,AlpacaDemo,OandaDemo,http_json
from jin_trading.live_once import run
from jin_trading.supervisor import Portfolio
from test_arbitrage import book,triangle


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'live.sqlite')
        self.client=MagicMock();self.client.id='kucoin'
        self.client.amount_to_precision.side_effect=lambda s,v:str(v)
        self.client.price_to_precision.side_effect=lambda s,v:str(v)
        self.client.fetch_balance.return_value={'free':{'USDT':5},'total':{'USDT':5}}
        self.client.request.return_value={'data':{'permission':'General,Spot'}}
        self.client.fetch_trading_fee.return_value={'taker':'.001'}
        self.feed=MagicMock();self.feed.exchange='kucoin'
        self.feed.pairs.return_value=['A-USDT','B-A','B-USDT']
        books={b.pair:b for b in triangle()}
        self.feed.book.side_effect=lambda p:books[p]
        self.broker=SpotBroker(self.client,self.feed)

    def tearDown(self):self.tmp.cleanup()

    def test_unarmed_precision_fees_and_identity(self):
        with self.assertRaises(ValueError):self.broker.submit('jin1','A-USDT','buy',D('1'),D('1'))
        self.broker.armed=True
        with self.assertRaises(ValueError):self.broker.book('A-USDT')
        self.broker.verified_fees['A-USDT']=(time.time(),D('.001'))
        self.assertEqual(self.broker.book('A-USDT').pair,'A-USDT')
        response={'id':'o','status':'closed','filled':1,'cost':1,'fees':[{'currency':'USDT','cost':'.001'}]}
        self.client.create_order.return_value=response
        self.assertEqual(self.broker.submit('jin1','A-USDT','buy',D('1'),D('1')),response)
        self.assertEqual(self.client.create_order.call_args.args[1:3],('limit','buy'))
        self.client.amount_to_precision.return_value='.9';self.client.amount_to_precision.side_effect=None
        with self.assertRaises(ValueError):self.broker.submit('jin2','A-USDT','buy',D('1'),D('1'))
        self.client.amount_to_precision.return_value='1';self.client.price_to_precision.side_effect=None
        self.client.price_to_precision.return_value='1.1'
        with self.assertRaises(ValueError):self.broker.submit('jin2','A-USDT','buy',D('1'),D('1'))
        with self.assertRaises(ValueError):SpotBroker(SimpleNamespace(id='other'),self.feed)

    def test_confirm_fill_fees_and_page_absence(self):
        order={'id':'o','status':'closed','filled':1,'cost':1}
        self.client.fetch_my_trades.return_value=[{'order':'o','amount':1,'fee':{'currency':'USDT','cost':'.001'}}]
        self.assertEqual(len(self.broker._fees(order,'A/USDT')['fees']),1)
        self.client.fetch_my_trades.return_value=[]
        with self.assertRaises(ValueError):self.broker._fees(order,'A/USDT')
        self.client.has={'fetchOpenOrders':True,'fetchClosedOrders':True}
        self.client.fetch_open_orders.return_value=[];self.client.fetch_closed_orders.return_value=[]
        self.assertIsNone(self.broker.lookup(None,'missing','A-USDT'))
        response=dict(order,clientOrderId='jin1',fee={'currency':'USDT','cost':'.001'})
        self.client.fetch_closed_orders.return_value=[response]
        self.assertEqual(self.broker.lookup(None,'jin1','A-USDT'),response)
        self.client.fetch_order.return_value=response
        self.assertEqual(self.broker.lookup('o','jin1','A-USDT'),response)
        self.broker.cancel('o','A-USDT');self.client.cancel_order.assert_called_once_with('o','A/USDT')

    def test_all_permission_adapters_and_held_equity(self):
        self.assertTrue(self.broker.permissions()['trade'])
        self.client.request.return_value={'data':{}}
        self.assertNotIn('withdraw',self.broker.permissions())
        self.client.id='binance'
        self.client.request.return_value={'enableReading':True,'enableSpotAndMarginTrading':True,'enableWithdrawals':False}
        self.assertFalse(self.broker.permissions()['withdraw'])
        self.client.id='bitget'
        self.client.request.return_value={'data':{'permType':'read-and-write','permissions':['uta_trade']}}
        self.assertTrue(self.broker.permissions()['trade'])
        self.client.id='kucoin';self.client.request.return_value={'data':{'permission':['General','Spot']}}
        portfolio=Portfolio(self.path,'live');portfolio.register(['kucoin'])
        self.client.fetch_balance.return_value={'free':{'USDT':4,'A':1},'total':{'USDT':4,'A':1}}
        result=self.broker.sync(portfolio,'kucoin')
        self.assertEqual(D(result['equity']),D('4.99'))
        self.assertTrue(portfolio.snapshot()['ready'])
        self.client.fetch_balance.return_value={'free':{},'total':{'USDT':-1}}
        with self.assertRaises(ValueError):self.broker.sync(portfolio,'kucoin')

    def test_readonly_five_usdt_check_never_places_an_order(self):
        result=check(self.client,self.feed,'5',self.path)
        self.assertEqual(result['mode'],'read-only')
        self.assertEqual(len(result['feasible']),1)
        self.client.create_order.assert_not_called()
        self.client.fetch_balance.return_value={'free':{'USDT':0},'total':{'USDT':5}}
        result=check(self.client,self.feed,'5',self.path)
        self.assertEqual(result['feasible'],[])

    def test_live_entrypoint_readonly_route_checks(self):
        with patch('jin_trading.live_once.PublicFeed',return_value=self.feed):
            result=run({'kucoin':self.client},'kucoin',['A-USDT','B-A','B-USDT'],'1',self.path)
        self.assertEqual(result['mode'],'read-only');self.client.create_order.assert_not_called()
        with self.assertRaises(ValueError):run({},'kucoin',[],1,self.path)

    def test_stock_forex_demo_fixed_hosts_and_client_ids(self):
        transport=MagicMock(return_value={'id':'123'})
        stock=AlpacaDemo('local-key','local-secret',transport)
        stock.account();stock.submit('jin1','AAPL','buy','1','100');stock.lookup(None,'jin1','AAPL');stock.cancel('123','AAPL')
        self.assertTrue(all(call.args[0]=='https://paper-api.alpaca.markets' for call in transport.call_args_list))
        self.assertEqual(transport.call_args_list[1].args[4]['client_order_id'],'jin1')
        fx=OandaDemo('local-token','demo-account',transport)
        fx.account();fx.submit('jin2','EUR-USD','sell','1','1.1');fx.lookup(None,'jin2','EUR-USD');fx.cancel('123','EUR-USD')
        order=transport.call_args_list[-3].args[4]['order']
        self.assertEqual(order['units'],'-1');self.assertEqual(order['priceBound'],'1.1')
        self.assertIn('%40jin2',transport.call_args_list[-2].args[1])
        for factory,args in ((AlpacaDemo,('','')),(OandaDemo,('',''))):
            with self.assertRaises(ValueError):factory(*args)
        with self.assertRaises(ValueError):stock.submit('id','AAPL','buy',0,100)
        with self.assertRaises(ValueError):fx.submit('id','EUR-USD','wrong',1,1)
