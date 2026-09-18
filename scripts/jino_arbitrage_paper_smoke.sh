#!/usr/bin/env bash
set -euo pipefail

CONFIG_NAME="conf_jino_paper_smoke.yml"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${HBOT_PASSWORD:-}" ]]; then
  echo "HBOT_PASSWORD is not set. Export the local Hummingbot keystore password first." >&2
  exit 4
fi

if ! command -v hbot >/dev/null 2>&1; then
  echo "hbot is not on PATH. Activate the hummingbot conda environment first." >&2
  exit 1
fi

# Recreate the dedicated smoke-test config every run so stale scaffolds cannot
# carry old defaults into a new test. This only removes the smoke-test file.
rm -f "conf/controllers/$CONFIG_NAME"

hbot create jino_cross_exchange_arbitrage --controller \
  --name "$CONFIG_NAME" \
  --set exchange_pair_1.connector_name=binance_paper_trade \
  --set exchange_pair_1.trading_pair=BTC-USDT \
  --set exchange_pair_2.connector_name=kucoin_paper_trade \
  --set exchange_pair_2.trading_pair=BTC-USDT \
  --set rate_connector=binance_paper_trade \
  --set quote_conversion_asset=USDT \
  --set safety_mode=paper \
  --set total_amount_quote=25 \
  --set max_trade_amount_quote=25 \
  --set min_profitability=0.005

echo "Starting paper-only Jino arbitrage smoke test..."
hbot start "$CONFIG_NAME" --controller
sleep 20
hbot status
echo "Stopping smoke test..."
hbot stop
