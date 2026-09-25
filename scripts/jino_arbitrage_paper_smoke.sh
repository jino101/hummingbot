#!/usr/bin/env bash
set -euo pipefail

CONFIG_NAME="conf_jino_paper_smoke.yml"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Make the helper self-contained: if it is launched outside the hummingbot
# conda environment, re-run it there with live stdin/stdout so the password
# prompt remains interactive on Codespaces/mobile terminals.
if [[ "${CONDA_DEFAULT_ENV:-}" != "hummingbot" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "conda is not available; activate the hummingbot environment first." >&2
    exit 1
  fi
  exec conda run --no-capture-output -n hummingbot bash "$0" "$@"
fi

if [[ -z "${HBOT_PASSWORD:-}" ]]; then
  read -r -s -p "Hummingbot password: " HBOT_PASSWORD
  echo
  export HBOT_PASSWORD
fi

if ! command -v hbot >/dev/null 2>&1; then
  echo "hbot is not on PATH. Activate the hummingbot conda environment first." >&2
  exit 1
fi

# Recreate the dedicated smoke-test config every run so stale scaffolds cannot
# carry old defaults into a new test. Controller starts are wrapped by hbot in
# a v2-script loader that uses the same filename, so remove BOTH generated
# config files from previous smoke-test runs before creating a fresh one.
rm -f "conf/controllers/$CONFIG_NAME" "conf/scripts/$CONFIG_NAME"

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
