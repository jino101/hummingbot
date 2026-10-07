# JIN Trading — Audit and implementation, 7 October 2026

Latest focused review: [AUDIT-2026-10-07.md](AUDIT-2026-10-07.md).
The supported coin universe, native CI and Docker build are confirmed; shared
real-money risk supervision, active-order reconciliation and the Sites bridge remain open.

Bases reviewed: `jino101/hummingbot` master `2bfaccc48dd49e71a5b6d9b3011808e127dd00cd`
and the user's actual development branch `chatgpt/arbitrage-bot`, commit
`2cb92e7aaf5b568d6b5ad25bc20a88fed1b95a7e`. The integrated change preserves the existing
55-file trading/mobile/Android stack and supplements it, rather than replacing it.

## Existing functionality confirmed

The development branch already contains `jino_cross_exchange_arbitrage`, public
observe and authenticated readonly/live gates, network compatibility and transfer
estimates, one-leg recovery rules, JSONL history, a token-protected mobile dashboard,
Android WebView source/APK workflow, shell launchers and targeted tests. These were
absent from master and were initially missed in the first inventory. This final
audit refers to the integrated development branch.

Additional issues found in that branch: the base-asset rebalance direction was
reversed (withdrawal must be from the buy venue; deposit to the sell venue), its
fee estimate used the wrong venue, cached live readiness lacked an execution-time
freshness check, and the mobile UI did not flag old snapshots or reject all failed
HTTP responses. Direction/fee selection, stale-readiness blocking, stale UI status,
HTML escaping and token comparison have now been corrected.
This is a focused review of the execution path, controller, connector interfaces,
CLI, Docker and project/test structure, not a security audit of every connector.

## Findings and resulting changes

| Finding | Implemented change | Remaining limitation |
|---|---|---|
| Arbitrage PnL percentage divided by base units rather than purchase notional | Divide by filled purchase quantity × actual buy price | Native regression CI passed; live account/runtime validation remains |
| Different quote currencies added/subtracted without conversion | Freeze quote conversion rate at opportunity evaluation; convert sell proceeds and fees | FX movement after the estimate is not continuously marked |
| Identical quote assets depended on an oracle entry | Return identity rate; reject absent/nonpositive/nonfinite oracle results | Oracle availability still required for unlike quotes |
| Fee query passed the same asset as base and quote | Pass actual pair assets; validate gas conversion input | Account-specific fees still need validation |
| Failed orders resubmitted the original full amount | Do not resubmit automatically; attempt cancellation, preserve known fills/order IDs; controller blocks after FAILED/POSITION_HOLD | A late fill or uncertain submission still requires reconciliation; this is not a complete hedge engine |
| Status could return None instead of list | Always return a status list | Native CI passed; production soak remains |
| No shared multi-bot portfolio ledger (existing limits are per controller) | Shared SQLite transactions, independent allocations totalling 5 USDT, deduplication and reinvestment | Controls affect only the JIN paper engine, not arbitrary Hummingbot instances |
| No triangular monitor | Three-asset closed routes, depth walking, fees, rounding, minimum size/notional and stale-book rejection | No sequential live triangular execution |
| Existing dashboard lacks per-bot paper controls | Authenticated responsive dashboard, per-bot paper Start/Stop, shared Not-Aus, PnL, opportunities, exchange errors, CSV | Existing cross-exchange observation shown; no live-mode toggle or external bot administration |
| Existing launchers/CI lack snapshot replay and shared paper deployment | Docker restart/persistent volume, bounded recording rotation, snapshot replay, focused CI | Docker build/Compose checks passed in CI; production runtime remains unverified |
| Early stop skipped cancellation and known-fill retention | Attempt both cancellations; preserve known exposure as POSITION_HOLD | Cancellation acknowledgement, late fills and restart reconciliation remain open |
| Live readiness accepted infinite market/account values | Reject nonfinite/invalid cap, price and balances | Real account probes and global risk integration remain open |

## Run the working paper application

Requires Python 3.12. The standalone application uses only Python's standard library;
Hummingbot itself does not need to be installed for the REST fallback.

```bash
# Run inside the repository root. Store the printed key privately.
export JIN_DASHBOARD_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
printf '%s\n' "$JIN_DASHBOARD_TOKEN"
python -m jin_trading.server
```

Open `http://127.0.0.1:8788` and enter your dashboard key. All bots start stopped
on the first launch. Public quotes are collected even while paper trading is stopped.
The example allocates **virtual** 2.5 USDT to KuCoin and 2.5 USDT to Binance;
it does not transfer or read your real 5 USDT on KuCoin. To put all paper capital
on KuCoin, replace the `bots` object with one KuCoin bot with budget `"5"` **before
creating the ledger**. Changing budgets after starting requires an explicit ledger
migration; restarting never overwrites balances or resets an emergency latch.

The existing dashboard remains on port 8787; this supplemental paper dashboard
uses port 8788. It reads `data/jino_observe_latest.json` from the existing observer.
Its Not-Aus also creates the existing controller runtime kill-switch file. Reset
clears **only** the new paper latch; it never removes the existing controller kill
switch or enables live trading. Use a shared data volume/directory to connect them.

No API keys are needed for public REST snapshots. Symbols that are unavailable,
whose rules cannot be interpreted, or whose minimums exceed the allocated amount
are excluded. With 5 USDT, and especially with two small allocations, no executable
opportunity may meet the minimums. This is a valid outcome, not an error to bypass.
Bitget supports non-USDT quote pairs when it can convert the USDT-denominated
minimum into quote units. Reference-ticker age and conversion-cache freshness still
need correction; this adapter remains paper-only.

### Maximum coin universe

The example now defaults to `pair_mode: auto`. Every 15 minutes, the public
symbol catalogue is refreshed. All supported active USDT pairs and all complete
three-asset routes returning to USDT on the same exchange enter the schedule.
There is no fixed coin-count cap. Binance spot eligibility is checked; Bitget
uses positive finite USDT conversion prices for non-USDT quote rules. Other disconnected
quote markets cannot use a USDT starting balance and are not scheduled.

`batch_size: 12` limits concurrent-cycle coverage, not the total universe. Complete
triangle groups are kept together and batches rotate fairly. The dashboard shows
catalogue/scheduled pair counts and the current batch. Larger universes take longer
to revisit; this is not simultaneous full-market monitoring or HFT. Requests are
spaced by at least 250 ms per exchange, HTTP 418/429/451 trigger cooldown, and an
outage aborts the remaining requests on that venue. Freshness, depth, fees and
minimum amounts still determine whether a candidate can be estimated.

Use `deny_pairs` to exclude pairs. To retain the original three-pair setup or use
the Hummingbot WebSocket bridge, set `pair_mode: manual`; `pairs` then controls the
subscriptions. The old controller's `observe_pairs` remains manually configured
and its live pair is never expanded automatically. Public symbol availability
does not prove deposit/withdrawal availability or token identity across venues.

The scanner now traverses connected currency edges instead of enumerating every
permutation of all books. Offline regression coverage includes 2,000 coins / 4,001
pairs, route-complete bounded batches, rotation, discovery outages and rate-limit
cooldown. Actual current exchange counts require reachable public APIs.

See [ROADMAP.md](ROADMAP.md) for the remaining work and acceptance criteria.

For Docker:

```bash
# Set JIN_DASHBOARD_TOKEN in the environment first, as above.
docker compose -f docker-compose.jin.yml up -d --build
```

The persistent named volume holds the ledger. The dashboard port binds to loopback.
For smartphone access, put it behind a private VPN or an authenticated HTTPS reverse
proxy on your chosen host. Do not expose the token over plain public HTTP.
A 24/7 host and its connection are not provisioned by this commit.

## Hummingbot WebSocket bridge

`scripts/jin_arbitrage_monitor.py` reads existing connectors' order books and
freshness metrics into the same ledger. It never calls buy/sell/order-submission
methods and rejects nonempty controller configurations. Set `pair_mode` to `manual`
in the JIN config before using this bridge. It needs a compiled Hummingbot
environment with working spot connectors, current trading rules and
freshness metrics. It uses the configured conservative fee assumptions, not verified
personal account fee tiers. Connecting a real connector may require keys in
Hummingbot even though this script places no orders.

```bash
hbot create jin_arbitrage_monitor --name jin_monitor.yml --with-defaults
# Review the generated config; controllers_config must remain empty.
hbot start jin_monitor.yml
# In a separate terminal, serve the SAME database without the REST writer:
python -m jin_trading.server --no-worker
```

Mount `jin_trading/` into the Hummingbot container at `/home/hummingbot/jin_trading`
and share its `data` volume if running in containers. Do not run both feed writers
against the same ledger: the REST and WebSocket sequence formats differ. The bridge
has syntax checks here but has not been run against compiled connectors.
Its scan interval is configurable down to 0.2 seconds; that does **not** make this
institutional HFT or promise that an order can be completed within that interval.

## Risk model

All amounts are in USDT in the virtual ledger; no leverage is used.

- Allocated budgets total 5 USDT rather than duplicating the same money per bot.
- Paper fills deploy at most 50% of the bot's current capital; a configured stress
  assumption also caps size against 1% of that capital. This is a sizing model, not
  a guarantee against larger real-world losses.
- Realized modelled profit is added to the next cycle's capital. Growth from 5 to
  10 USDT doubles absolute budgets while percentages stay fixed.
- The shared cutoff is 10% of total paper equity at the start of the Berlin calendar
  day. The initial baseline is the first observation after startup, and at rollover
  it is the first observation of the new day, not an exact midnight valuation.
- The emergency latch persists across restarts and day changes. Reset is explicit;
  bots remain stopped after reset. Reset is rejected while the day's loss threshold
  remains breached.
- Start/Stop prevents modelled fills. Not-Aus does **not** cancel real exchange
  orders: the new app has no real-order capability.
- Cross-exchange estimates assume prefunded inventory and omit transfer/rebalancing
  cost. They are informational and are not automatically paper-filled. Transfer
  networks, suspensions and usable account inventories are not yet validated.

## Recording and replay

Add `"record_path": "data/jin-books.jsonl"` to a copy of the config and pass it with
`--config`. Records rotate at approximately 10 MB, retaining the current and previous
file. Replay requires a fresh SQLite path and refuses to overwrite an existing ledger:

```bash
python -m jin_trading.replay data/jin-books.jsonl --db data/replay-new.sqlite
```

Replay evaluates historical snapshots sequentially without future prices. Paper
fills are instant estimates with depth and buffers; unspent/rounded dust is
conservatively discarded. It does not model queue position, exchange latency,
partial fills between legs, withdrawals or real balances. It cannot establish
live profitability. Same-sequence deduplication prevents repeatedly filling an
unchanged snapshot, but no realistic queue-consumption model is present.

## Verification

```bash
python -m unittest discover -s tests_jin -v
python -m compileall -q jin_trading scripts/jin_arbitrage_monitor.py
```

The focused tests cover fees/limits/depth, malformed and stale data, shared budgets,
concurrent duplicate fills, restart/day rollover, API authentication, feed parsing,
worker failures, replay and executor regressions. The isolated executor tests
compile the unchanged class bodies with a base harness because Cython dependencies
are absent. These tests supplement, not replace, native Hummingbot tests.

Observed here:

- At starting revision `c2bb5e7`, GitHub CI passed 43 focused unittest tests,
  32 pure/mobile tests and 198 targeted native tests, with 89% coverage for
  `jin_trading`. These groups are not all independent.
- The October 7 safety corrections passed 46 local unittest tests and twelve
  invalid-market/account scenarios. GitHub CI also passed 212 targeted native
  tests, 46 unittest tests, 44 pure/mobile tests and Docker checks, with 89%
  `jin_trading` coverage. Separate native/Paper runs are linked in the audit.
- Syntax compilation, JavaScript syntax validation and `git diff --check` pass.
- Dashboard authentication/control endpoints pass HTTP integration tests. A visual
  mobile-browser test remains unverified: Chromium was absent and its download
  was blocked/truncated in this environment.
- The local environment lacks compiled connectors and pytest. Targeted native
  executor/controller/provider/loader tests were instead verified through GitHub CI.
- Actual public-API probes: KuCoin timeout, Bitget timeout, Binance HTTP 451.
  Fixture-based parsing is tested; reachable real feeds still need a host test.
- Docker image build and Compose configuration passed GitHub CI. A running service,
  restart/backup test and production deployment remain open.
- No real order was submitted and no production service was published.

## Work still required for the complete requested system

1. Validate public feeds and the WebSocket bridge in a complete Hummingbot runtime;
   verify current account fees and symbol rules.
2. Build live triangular execution with per-leg fills, residual-asset reconciliation,
   timeout/partial-fill recovery and integration tests. Connect real shared balances
   and open positions to global risk accounting before enabling multiple live bots.
3. Validate the existing private account/network/readiness checks with real readonly
   credentials, add Bitget support to those authenticated checks, and reconcile
   inventories/rebalancing in live operation. The generic executor fixes alone do
   not finish this.
4. Connect existing Hummingbot market-making/directional strategies to the central
   supervisor. The dashboard currently runs multiple triangular PAPER bots; arbitrary
   live Hummingbot bots and scalping/market-making are not centrally controlled.
5. Select an equities/Forex broker and implement its data/order adapter, market hours,
   denomination conversion, contract sizing and demo-account tests. The crypto
   connectors cannot trade ordinary shares/Forex accounts.
6. Provision a server, HTTPS/VPN, secrets, backups and operational monitoring. Check
   restart reconciliation and notifications there. Replit search found no matching
   trading app; none was silently created or deployed.
7. Test streaming reconnection, clock drift, throttling and measured end-to-end
   execution latency. Low-latency work is still separate from an HFT claim.

No additional ChatGPT plugin is necessary for the code in this commit. Exchange and
broker accounts/credentials plus a chosen host are the remaining external inputs.
