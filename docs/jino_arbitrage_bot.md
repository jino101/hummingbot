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

- Verify the paper smoke test in a real Codespace/runtime.
- Add exchange-specific live deposit/withdraw/network-status adapters.
- Add stale-quote / quote-age protection to the live scanner data source.
- Add tested partial-fill / one-leg recovery policy.
- Run a meaningful paper soak test before any real exchange keys are connected.
- Keep withdrawal permission disabled on any future live API keys.
