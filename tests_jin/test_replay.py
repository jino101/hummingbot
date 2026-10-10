import json
import tempfile
import time
import unittest
from pathlib import Path

from jin_trading.replay import record, replay
from jin_trading.worker import load_config
from test_arbitrage import triangle


class ReplayTests(unittest.TestCase):
    def test_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'books.jsonl';db=Path(tmp)/'replay.sqlite';now=time.time()
            record(path,triangle(now),now)
            record(path,triangle(now),now+1)
            result=replay(path,load_config('jin_trading/config.example.json'),db)
            self.assertEqual(result['events'],2)
            self.assertEqual(result['paper_trades'],1)
            with self.assertRaises(ValueError):replay(path,load_config('jin_trading/config.example.json'),db)

    def test_rotation_and_out_of_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'books.jsonl';now=time.time()
            record(path,triangle(now),now,max_bytes=1)
            record(path,triangle(now),now,max_bytes=1)
            self.assertTrue(Path(str(path)+'.1').exists())
            record(path,triangle(now),now-1)
            with self.assertRaises(ValueError):replay(path,load_config('jin_trading/config.example.json'),Path(tmp)/'replay.sqlite')
