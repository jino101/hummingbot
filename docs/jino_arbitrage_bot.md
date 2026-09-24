# Jino Hummingbot Arbitrage Bot

This branch turns the stock Hummingbot arbitrage controller into a safer base for a custom cross-exchange arbitrage bot.

## Current scope

- Cross-exchange spot arbitrage using Hummingbot Strategy V2 and `ArbitrageExecutor`.
- Paper mode is the default and refuses live connectors unless `safety_mode: live` is set explicitly.
- Default paper venues: `binance_paper_trade` and `kucoin_paper_trade`.
- Default pair: `BTC-USDT`.
- Default minimum profitability: 0.5%.
- Per-trade quote cap.
- Manual kill switch support.
- Daily realized-loss limit.
- Daily completed-trade limit.

## Why this base

Hummingbot's `ArbitrageExecutor` already queries resulting prices for the requested amount on both venues, includes trading/transaction costs in the profitability calculation, validates balances, and places buy/sell market orders. The custom controller adds safety gates around executor creation.

## Paper-test flow

After installing Hummingbot from source:

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate hummingbot
export HBOT_PASSWORD='<your local keystore password>'

hbot create jino_cross_exchange_arbitrage \
  --name conf_jino_arbitrage.yml \
  --with-defaults

hbot config
hbot start conf_jino_arbitrage.yml
hbot status
hbot logs -f
hbot stop
```

Do not commit secrets or exchange API keys.

## Live-trading gate

The controller will reject real connector names while `safety_mode=paper`. Before a future live test, all of the following should be true:

1. Paper mode has run reliably for a meaningful period.
2. Both exchange connectors are verified for the desired spot pair.
3. API keys have only read/trade permissions; withdrawal permission stays disabled.
4. Capital is pre-positioned on both venues.
5. Trade caps and daily loss limits are set conservatively.
6. Deposit/withdrawal/network status checks have been added for the selected exchanges.
7. Partial-fill / one-leg recovery behavior has been tested.

## Remaining roadmap

### Phase A — robust two-exchange paper arbitrage

- Validate current controller through CI and Codespaces.
- Add explicit tests for profitability thresholds and imbalance handling.
- Add structured status output for current opportunity and risk gate.

### Phase B — scanner

- Discover common spot pairs across configured exchanges.
- Rank opportunities by net spread after fees and amount-aware prices.
- Add configurable allow/deny lists and minimum liquidity rules.
- Scanner-only mode must never submit orders.

### Phase C — transfer/network intelligence

- Exchange-specific adapters for deposit status, withdrawal status, supported chains, and withdrawal fee.
- Match network aliases safely (for example ERC20/Ethereum), never by symbol alone.
- Treat unknown or stale network status as non-transferable.

### Phase D — execution safety

- Slippage ceiling.
- Max quote-age / stale-data gate.
- Partial-fill and one-leg recovery/hedge policy.
- Rebalancing recommendations; no automatic withdrawal by default.

### Phase E — triangular arbitrage

- Same-exchange path discovery (A→B→C→A).
- Three-leg fee/slippage calculation.
- Paper simulation before any live execution.

### Phase F — dashboard

- Opportunity table: buy venue, sell venue, pair, buy price, sell price, gross spread, estimated fees, net spread, max safe amount, transferability status.
- Scanner / manual / automatic modes.
- Kill switch and risk settings.
- Trade history with expected vs realized PnL.

## Safety note

This project is experimental trading software. A paper result is not evidence of live profitability. Real execution adds latency, partial fills, outages, changing fee tiers, exchange restrictions, and capital risk.


## Current implementation status

Completed on this branch:

- Safety-first cross-exchange controller with paper/live separation.
- Paper defaults for Binance Paper and KuCoin Paper.
- Per-trade cap, daily realized-loss limit, completed-trade limit, and manual kill switch.
- Net opportunity calculator with fees, slippage, and depth caps.
- Transfer-network alias matching and fail-closed deposit/withdraw status semantics.
- Rebalance transfer-fee estimate and optional post-rebalance profitability filter.
- Scanner-only common-pair discovery with allow/deny lists.
- Fail-safe one-leg recovery decision helper; exposed/partial fills escalate to manual intervention unless auto-hedge is explicitly enabled by a future integration.
- Regression fix so the CLI selects the custom controller config class rather than an imported base class.
- Targeted unit tests and a dedicated Jino Arbitrage CI workflow.
- Paper smoke-test helper at `scripts/jino_arbitrage_paper_smoke.sh`.

### One-command paper smoke test

After pulling the branch and activating the Hummingbot conda environment:

```bash
read -s -p "Hummingbot password: " HBOT_PASSWORD; echo; export HBOT_PASSWORD
bash scripts/jino_arbitrage_paper_smoke.sh
```

The helper explicitly forces paper connectors and a 25 USDT test amount, prints status after 20 seconds, and then stops the bot. It does not store or print the password.

### Remaining before live-ready

- Paper smoke test verified in Codespaces: controller starts, appears in status, and stops cleanly.
- Add exchange-specific live deposit/withdraw/network-status adapters.
- Add stale-quote / quote-age protection to the live scanner data source.
- Integrate the tested one-leg recovery decision policy into live executor event handling; automatic hedging remains disabled by default.
- Run a meaningful paper soak test before any real exchange keys are connected.
- Keep withdrawal permission disabled on any future live API keys.


### Longer paper soak test

A longer paper validation helper is available at `scripts/jino_arbitrage_paper_soak.sh`.

By default it runs for 5 minutes, prints periodic status, scans the recent structured log for
ERROR/CRITICAL entries, and stops the bot through a shell trap even if the script is interrupted.

```bash
read -s -p "Hummingbot password: " HBOT_PASSWORD; echo; export HBOT_PASSWORD
JINO_SOAK_SECONDS=300 JINO_SOAK_STATUS_INTERVAL=30 \
  bash scripts/jino_arbitrage_paper_soak.sh
```

This is still a paper-only stability test. Passing it does not prove profitable execution.

### Current milestone

Completed and verified:
- targeted test suite previously reached 81 passing tests in Codespaces
- runtime controller-loader regression test passed
- short Binance Paper / KuCoin Paper smoke test starts and stops cleanly
- controller safety gates and paper/live separation are implemented
- pure scanner math covers fees, slippage, stale quotes, liquidity caps, and rebalance fee estimates

Implemented on GitHub and awaiting the next Codespaces pull/test:
- stricter live-mode validation
- same-exchange and mismatched-base rejection
- structured safety status for a future dashboard
- executor-proposal and daily trade-limit regression tests
- controller-class resolution hardening
- longer paper soak helper
- expanded CI target list

Next runtime milestone:
1. Pull the latest branch.
2. Run the expanded targeted tests.
3. Run the longer paper soak.
4. Confirm both paper connectors stay healthy and no ERROR/CRITICAL log entries appear.
5. Observe at least one full paper arbitrage execution path before any live-key work.


### Verified paper milestones (Codespaces)

As of 2026-09-22, the following runtime milestones have been observed successfully in Codespaces:

- Five-minute Binance Paper / KuCoin Paper soak completed with no ERROR/CRITICAL entries from that run.
- Deterministic paper execution-path test reached order creation, fill/completion handling, clean shutdown, and reported a completed paper trade.
- Dedicated Jino CI and repository CI were green on the branch after the paper-order tracking fixes.

A single helper now runs the full paper validation sequence:

```bash
bash scripts/jino_arbitrage_paper_validate.sh
```

This runs the targeted regression suite, the soak test, and the deterministic paper execution-path test. Passing it is a software-validation milestone only; it does not establish live profitability or exchange-transfer availability.

### Next milestone

Before any live-key test, finish and validate:

1. exchange-specific deposit/withdraw/network-status adapters with fail-closed behavior on unknown or stale status;
2. one-leg/partial-fill recovery integration, with automatic hedging disabled by default;
3. a small live-readiness gate that refuses live mode unless those checks are available and healthy;
4. only then, an explicitly opted-in tiny live test with withdrawal permissions disabled.


### Live-readiness and recovery implementation

The branch now contains a fail-closed live gate for the Binance/KuCoin path:

- authenticated API-permission probes;
- base-asset deposit/withdraw network discovery and network alias normalization;
- withdrawal-fee conversion to the configured quote asset;
- common bidirectional rebalance-network requirement;
- connector-health and pre-positioned balance checks;
- API keys must support read + spot trading;
- API withdrawal permission must be disabled;
- unknown, stale, unsupported, or failed readiness probes block new live executors;
- Jino-created arbitrage executors enable one-leg recovery handling;
- a failed/cancelled leg cancels a still-pending opposite leg;
- a filled or partially-filled exposed leg is preserved as POSITION_HOLD for explicit operator handling;
- automatic third-order hedging is intentionally disabled.

The tiny live harness is intentionally opt-in and capped:

```bash
JINO_CONFIRM_TINY_LIVE=I_UNDERSTAND_LIVE_TRADING \
JINO_LIVE_QUOTE_AMOUNT=10 \
bash scripts/jino_arbitrage_tiny_live.sh
```

The helper refuses amounts above 25 USDT, limits the controller to one completed trade, and stops if
the live-readiness gate reports false. It must not be run until exchange keys are configured with
withdrawal permission disabled.

The live harness itself can be syntax/unit tested without real credentials. A real live execution
cannot be validated in CI because it requires the operator's exchange accounts, API keys, balances,
and current exchange/network state.
