# External project reuse ledger (paper-only)

This log distinguishes upstream **dependencies/API patterns** from copied source.
No third-party implementation file was pasted into the new modules.

| Needed capability | Source | License checked | Integration status | Project file |
|---|---|---|---|---|
| Unified public CEX REST markets | [CCXT](https://github.com/ccxt/ccxt) | MIT ([license](https://github.com/ccxt/ccxt/blob/master/LICENSE.txt)) | Python dependency/API; not vendored | `ccxt_feed.py` |
| Executable L2 orderbook amounts | [CCXT fetch_order_book](https://docs.ccxt.com/#/?id=order-book) | MIT | Python dependency/API; own normalization and depth calculation | `depth_scanner.py` |
| Original CEX streaming | [Hummingbot](https://github.com/hummingbot/hummingbot) | review upstream file-specific obligations | Existing project's connectors available; not newly imported into JIN V2 | Hummingbot fork |
| DEX Jupiter SDK | [0xTaoDev/jupiter-python-sdk](https://github.com/0xTaoDev/jupiter-python-sdk) | MIT | Candidate only, NOT integrated; API compatibility/key requirements must be verified | `solana.py` placeholder |
| Streaming books | [Cryptofeed](https://github.com/bmoscon/cryptofeed) | AGPLv3+ / attribution | Candidate only, NOT imported or copied | — |
| Backtesting architecture | [Freqtrade](https://github.com/freqtrade/freqtrade) | GPLv3 | Reference only; NOT imported | — |
| Event engine architecture | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | LGPLv3 | Reference only; NOT imported | — |

## Newly implemented checkpoint
- `python -m pip install ccxt`
- `python -m unittest jin_arbitrage_v2.test_depth_scanner jin_arbitrage_v2.test_ccxt_feed jin_arbitrage_v2.test_streams jin_arbitrage_v2.test_selftest -v`
- `python -m jin_arbitrage_v2.run_depth_scanner --venues kraken,kucoin,bitget --symbols SOL/USDT,BTC/USDT`

**Not tested against a live API during this integration.** The scanner uses sequential REST snapshots. A live trade requires verified symbol and network status, custody, synchronized quotes, exact venue fees, minimum order sizing, realistic fill/latency simulations, and full risk controls. Gross/net profits printed are *estimates* and cannot be interpreted as realized profit. Trades are never submitted.

## Remaining original-V2 work, highest priority
1. Run tests and fix runtime incompatibilities.
2. Improve feed status/reconnect and determine stale snapshots on receipt.
3. Verified deposit/withdrawal chain compatibility; exchange market status.
4. Concurrency and rate limits, orderbook depth across requested markets, paper fill/partial simulation.
5. Solana DEX public quotes and meme token discovery with token verification.
6. Triangular and CEX/DEX round-trip fees, latency, balances and transfer costs.
7. Mobile dashboard and persistence. Read-only hosting and monitoring.

The 40 optional ideas are deferred.


## Block 2 upstream verification (2026-10-08)
- Jupiter: official `jup-ag/docs` confirms current Swap API paths and API-key requirement; Tokens API V2 is documented for token metadata/discovery. JIN has not copied Jupiter implementation source and has not enabled transaction signing.
- Raydium: official `raydium-io/raydium-sdk-V2-demo` contains current swap/route examples. Used as architecture/API reference only; no source copied.
- Orca: official `orca-so/whirlpools` exposes swap quote/instruction APIs. Used as architecture/API reference only; no source copied.
- Meteora: official `MeteoraAg` docs/SDK document DLMM swap quotes and Data API. Used as architecture/API reference only; no source copied.
- Added local network-free unit tests for `costs.py`, `market_status.py`, and `triangular_depth.py`. These tests are committed but are not claimed as executed until CI/runtime reports a result.
- Provider-neutral meme-token discovery write was attempted but the connector safety gate rejected that write, so it is deliberately not marked implemented.
