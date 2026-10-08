# CCXT read-only scanner (Blitzversion)

Dependency: **CCXT**, MIT license, https://github.com/ccxt/ccxt .
The CCXT license is available upstream: https://github.com/ccxt/ccxt/blob/master/LICENSE.txt .
We import the installed package; do not vendor third-party code.

## Install

```sh
python -m pip install ccxt
```

## Offline checks (no exchange calls)

```sh
python -m unittest jin_arbitrage_v2.test_selftest jin_arbitrage_v2.test_streams jin_arbitrage_v2.test_ccxt_feed -v
```

## Read-only spot scan

```sh
python -m jin_arbitrage_v2.run_ccxt_scanner --venues kraken,kucoin,bitget --symbols BTC/USDT,SOL/USDT
```

**No credentials; no order placements.** These are HTTP snapshots rather than synchronized real-time books. Exchange geographic restrictions, blocked pairs, rate limits, fees, stale timestamps, orderbook depth, transfer/network costs, slippage, balance availability and partial fills can invalidate a quoted spread. The current fee input is an unverified estimate. Do not consider PAPER_CANDIDATE executable or a profit guarantee.

Cryptofeed upstream: https://github.com/bmoscon/cryptofeed (AGPL-3.0+ plus attribution clause). It is **not** vendored or imported here; evaluate license obligations before adding it.

Next: test REST availability, then implement venue status and orderbook-derived executable sizes before any paper P&L accounting.
