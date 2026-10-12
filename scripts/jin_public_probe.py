"""Bounded public-only KuCoin WebSocket smoke test; never constructs an account."""
import argparse
import asyncio
import json
import time


async def probe(seconds=30):
    import ccxt.pro as ccxt
    client = ccxt.kucoin({'enableRateLimit': True, 'timeout': 10000,
                          'options': {'defaultType': 'spot'}})
    pairs = ['BTC/USDT', 'ETH/USDT', 'ETH/BTC']
    report = {'exchange': 'kucoin', 'ccxt_version': ccxt.__version__,
              'public_only': True, 'duration_seconds': seconds, 'markets': {}}
    async def watch(pair):
        samples = report['markets'][pair] = {'updates': 0, 'fresh_updates': 0, 'min_age_seconds': None, 'max_age_seconds': None}
        previous = None
        while True:
            book = await client.watch_order_book(pair, 20)
            nonce = book.get('nonce')
            if nonce is not None and nonce == previous:
                continue
            previous = nonce
            samples['updates'] += 1
            stamp = book.get('timestamp')
            if stamp is not None:
                age = time.time() - stamp / 1000
                samples['fresh_updates'] += int(0 <= age <= 3)
                samples['min_age_seconds'] = min(age, samples['min_age_seconds'] if samples['min_age_seconds'] is not None else age)
                samples['max_age_seconds'] = max(age, samples['max_age_seconds'] if samples['max_age_seconds'] is not None else age)
    tasks = []
    started = time.monotonic()
    try:
        await client.load_markets()
        before = time.time()
        server_time = await client.fetch_time()
        after = time.time()
        report['clock_offset_seconds'] = server_time / 1000 - (before + after) / 2
        report['clock_sample_roundtrip_seconds'] = after - before
        tasks = [asyncio.create_task(watch(pair)) for pair in pairs]
        await asyncio.sleep(seconds)
        errors = [type(task.exception()).__name__ for task in tasks if task.done() and not task.cancelled() and task.exception()]
        report['errors'] = errors
        report['stream_received_all'] = all(report['markets'].get(pair, {}).get('updates', 0) > 0 for pair in pairs)
        report['fresh_timestamps_observed_all'] = all(report['markets'].get(pair, {}).get('fresh_updates', 0) > 0 for pair in pairs)
    except Exception as exc:
        report['errors'] = [type(exc).__name__]
        report['stream_received_all'] = False
        report['fresh_timestamps_observed_all'] = False
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.close()
        report['elapsed_seconds'] = time.monotonic() - started
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--require-fresh', action='store_true', help='Also require actual timestamp ages in the existing 0..3 second window')
    args = parser.parse_args()
    if not 5 <= args.seconds <= 300:
        parser.error('seconds must be between 5 and 300')
    result = asyncio.run(probe(args.seconds))
    print(json.dumps(result, indent=2, allow_nan=False))
    okay = result['stream_received_all'] and not result['errors']
    if args.require_fresh:
        okay = okay and result['fresh_timestamps_observed_all']
    raise SystemExit(0 if okay else 1)
