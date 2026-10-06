import json
import tempfile
import threading
import unittest
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
