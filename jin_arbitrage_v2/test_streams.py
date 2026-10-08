"""Offline tests: no network, API keys, or live orders."""
import asyncio
import unittest
from .live_streams import merge_streams, BinanceBookTickerStream, BybitTickerStream

class TestStreams(unittest.TestCase):
    def test_binance_parser(self):
        q=BinanceBookTickerStream().parse_message({"b":"115.40","a":"115.41","B":"2","A":"3"})
        self.assertEqual(q.venue,"binance")
        self.assertEqual(q.symbol,"SOL/USDT")
        self.assertAlmostEqual(q.bid,115.4)

    def test_bybit_parser(self):
        stream=BybitTickerStream()
        self.assertIsNone(stream.parse_message({"op":"subscribe","success":True}))
        q=stream.parse_message({"topic":"tickers.SOLUSDT","ts":1234,
            "data":{"bid1Price":"115.4","ask1Price":"115.5","bid1Size":"2","ask1Size":"3"}})
        self.assertEqual(q.venue,"bybit")
        self.assertAlmostEqual(q.ask,115.5)

    def test_merge_yields_all_quotes(self):
        async def source(items):
            for item in items:
                yield item
        async def run():
            result=[]
            async for value in merge_streams(source([1,2]),source([3])):
                result.append(value)
            return sorted(result)
        self.assertEqual([1,2,3],asyncio.run(run()))

    def test_merge_surfaces_failure(self):
        async def failing():
            yield 1
            raise ValueError("disconnected")
        async def run():
            async for _ in merge_streams(failing()):
                pass
        with self.assertRaisesRegex(RuntimeError,"Market-data stream failed"):
            asyncio.run(run())

if __name__=="__main__":
    unittest.main()
