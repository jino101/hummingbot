import json
import tempfile
import threading
import unittest
import csv
import io
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jin_trading.server import make_server
from jin_trading.store import Store


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'paper.sqlite')
        self.store.configure({'bot':'5'})
        self.token='x'*32
        self.server=make_server(self.store,self.token,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.thread.join();self.server.server_close();self.tmp.cleanup()

    def request(self,path,method='GET',auth=True,data=None):
        headers={'Authorization':'Bearer '+self.token} if auth else {}
        return urlopen(Request(self.url+path,headers=headers,method=method,data=data),timeout=3)

    def test_auth_assets_and_export(self):
        with self.assertRaises(HTTPError) as caught:self.request('/api/state',auth=False)
        self.assertEqual(caught.exception.code,401)
        for path in ('/','/dashboard.js','/dashboard.css'):
            with self.request(path,auth=False) as response:
                self.assertEqual(response.status,200)
                self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        with self.request('/api/state') as response:
            self.assertFalse(json.load(response)['live_available'])
        with self.request('/api/trades.csv') as response:self.assertIn(b'bot',response.read())

    def test_controls_emergency_and_bad_paths(self):
        with self.request('/api/bots/bot/start','POST') as response:self.assertTrue(json.load(response)['bots'][0]['enabled'])
        with self.request('/api/halt','POST') as response:self.assertTrue(json.load(response)['halt'])
        with self.assertRaises(HTTPError):self.request('/api/bots/bot/start','POST')
        with self.request('/api/reset','POST') as response:self.assertFalse(json.load(response)['halt'])
        with self.request('/api/bots/bot/stop','POST') as response:self.assertEqual(response.status,200)
        for path in ('/api/live','/api/bots/bot/delete','/api/bots/absent/start'):
            with self.assertRaises(HTTPError):self.request(path,'POST')
        with self.assertRaises(HTTPError):self.request('/api/state','POST',data=b'{}')
        with self.assertRaises(HTTPError):self.request('/unknown')

    def test_short_token_rejected(self):
        with self.assertRaises(ValueError):make_server(self.store,'weak',port=0)

    def test_cors_allows_only_explicit_origin_and_preflight(self):
        allowed='https://example.test';self.server.allowed_origins.add(allowed)
        request=Request(self.url+'/api/state',headers={'Authorization':'Bearer '+self.token,'Origin':allowed})
        with urlopen(request) as response:self.assertEqual(response.headers['Access-Control-Allow-Origin'],allowed)
        request=Request(self.url+'/api/state',headers={'Origin':allowed},method='OPTIONS')
        with urlopen(request) as response:self.assertEqual(response.status,204)
        for method in ('GET','OPTIONS'):
            request=Request(self.url+'/api/state',headers={'Authorization':'Bearer '+self.token,'Origin':'https://evil.test'},method=method)
            with self.assertRaises(HTTPError) as caught:urlopen(request)
            self.assertEqual(caught.exception.code,403)
        with self.assertRaises(ValueError):make_server(self.store,self.token,port=0,allowed_origins=['https://example.test/path'])

    def test_export_includes_more_than_dashboard_rows(self):
        with self.store.connect() as db:
            db.executemany('INSERT INTO trades(bot,timestamp,sequence,input,output,route) VALUES (?,?,?,?,?,?)',
                           [('bot',1,str(i),'1','1.1','[]') for i in range(125)])
        self.assertEqual(len(self.store.snapshot()['trades']),100)
        with self.request('/api/trades.csv') as response:
            self.assertEqual(len(list(csv.DictReader(io.StringIO(response.read().decode())))),125)

    def test_encoded_id_and_non_object_observation(self):
        self.server.observation_path=Path(self.tmp.name)/'observation.json'
        self.server.observation_path.write_text('[]')
        with self.request('/api/existing/status') as response:self.assertFalse(json.load(response)['available'])
        with self.request('/healthz',auth=False) as response:self.assertEqual(response.status,200)

    def test_worker_journal_state_and_reconcile_endpoint(self):
        from jin_trading.worker import Worker,load_config
        config=load_config('jin_trading/config.example.json');config['bots']={'bot':{'exchange':'kucoin','budget':'5'}}
        self.server.worker=Worker(self.store,config)
        with self.request('/api/state') as response:
            state=json.load(response);self.assertIn('portfolio',state);self.assertIn('growth',state)
        with self.request('/api/orders') as response:self.assertEqual(json.load(response),[])
        with self.request('/api/reconcile','POST') as response:self.assertEqual(json.load(response),[])
        with self.request('/api/bots/bot/start','POST') as response:self.assertEqual(response.status,200)
        with self.request('/api/halt','POST') as response:self.assertTrue(json.load(response)['portfolio']['halt'])

    def test_inventory_acceptance_requires_terminal_orders_and_keeps_latch(self):
        from jin_trading.worker import Worker,load_config
        config=load_config('jin_trading/config.5usdt.json');config['bots']={'bot':{'exchange':'kucoin','budget':'5'}}
        self.server.worker=Worker(self.store,config);portfolio=self.server.worker.portfolio
        run=portfolio.reserve('bot',[('bot','USDT','1','1')])
        client=portfolio.prepare(run,'bot','A-USDT','buy','1','1')
        portfolio.submitting(client);portfolio.unknown(client,'response missing');portfolio.finish(run,False,'unknown')
        path='/api/runs/'+run+'/accept-reconciled-inventory'
        with self.assertRaises(HTTPError):self.request(path,'POST')
        portfolio.observe(client,{'id':'exchange','status':'closed','filled':'1','cost':'1',
                                 'fees':[{'currency':'USDT','cost':'.001'}]})
        with self.request(path,'POST') as response:self.assertTrue(json.load(response)['halt'])
        self.assertEqual(portfolio.orders(True),[])
        with self.request('/api/reset','POST') as response:self.assertFalse(json.load(response)['halt'])

    def test_existing_snapshot_and_emergency_bridge(self):
        observation=Path(self.tmp.name)/'observation.json'
        kill=Path(self.tmp.name)/'runtime.kill'
        self.server.observation_path=observation
        self.server.kill_switch_path=kill
        with self.request('/api/existing/status') as response:self.assertFalse(json.load(response)['available'])
        observation.write_text('{"timestamp": 1, "mode":"observe"}')
        with self.request('/api/existing/status') as response:self.assertTrue(json.load(response)['stale'])
        observation.write_text('broken')
        with self.request('/api/existing/status') as response:self.assertFalse(json.load(response)['available'])
        with self.request('/api/halt','POST') as response:self.assertTrue(kill.exists())
        with self.request('/api/reset','POST') as response:self.assertTrue(kill.exists())
