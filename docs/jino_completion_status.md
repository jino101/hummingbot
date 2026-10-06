# Jino completion status

This branch is organized around four safety stages:

1. **paper** - simulated balances/orders only.
2. **observe** - public Binance/KuCoin market data only, no exchange credentials, no executors/orders.
3. **readonly** - authenticated metadata with read-only API keys; no executors/orders.
4. **live** - real spot trading only after explicit configuration and live-readiness checks.

## Implemented

- Cross-exchange BTC-USDT arbitrage controller.
- Paper validation, smoke, soak, and deterministic execution-path tests.
- Amount-aware order-book checks, taker fee/slippage estimates, transfer network checks.
- Deposit/withdraw network compatibility and transfer ETA estimation.
- One-leg/partial-fill recovery safeguards.
- Daily trade/loss caps and manual/runtime kill switches.
- Credential-free public-market observe mode.
- Authenticated read-only mode with a hard execution block.
- Observation JSONL history, latest snapshot, and summary statistics.
- Mobile-friendly dashboard with current opportunity, history, safety state, and kill-switch engage action.
- Installable Android WebView app source.
- GitHub Actions for core Jino tests and Android APK builds.

## Deliberately not automatic

The following need the account owner because GitHub must not receive private exchange credentials:

- creating Binance/KuCoin API keys;
- entering Hummingbot keystore/API credentials;
- deciding whether to enable spot-trading permission;
- the first real-money trade;
- choosing a permanent server/hostname and exposing it securely over HTTPS;
- installing the generated APK on the phone.

Withdrawal permission should remain disabled for this project.

## Mobile dashboard

Start the data collector:

```bash
bash scripts/jino_arbitrage_observe.sh
```

In another terminal start the dashboard:

```bash
bash scripts/jino_dashboard.sh
```

The dashboard exposes status/history and can engage the kill switch. It intentionally has no endpoint to start live trading or disable the kill switch.

### Dashboard access token

On every dashboard start, a random `JINO DASHBOARD TOKEN` is printed unless
`JINO_DASHBOARD_TOKEN` is explicitly supplied. Status/history endpoints require this bearer token.
The web UI asks for the token and stores it only in the browser session. Keep the Codespaces port
private. In Codespaces the launcher also prints the HTTPS forwarding URL that can be entered in the
Android app.

## Authenticated read-only stage

After read-only exchange keys are configured:

```bash
bash scripts/jino_arbitrage_readonly.sh
```

This stage can inspect authenticated balances/network metadata while `determine_executor_actions()` remains hard-blocked.

## Android

The `Jino Android` GitHub workflow builds `jino-android-debug` as an APK artifact. The app accepts only an HTTPS dashboard URL and does not store exchange API keys.


## 6 October 2026 extension

The existing controller/mobile/Android stack is preserved. See
[JIN integration audit](jin/README.md) for triangular paper bots, shared virtual
5-USDT allocations with a persistent 10% daily cutoff, reinvestment, replay, a
supplemental dashboard on port 8788, WebSocket bridge and executor/network fixes.
The new dashboard reads this stack's observation file and can engage its runtime
kill switch. Its reset affects only the new paper ledger. Real multi-bot portfolio
supervision, live triangular execution, stocks/Forex and a permanent host remain open.
