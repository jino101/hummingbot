#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIG_NAME="conf_jino_observe.yml"
AMOUNT="${JINO_OBSERVE_QUOTE_AMOUNT:-25}"

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

rm -f "conf/controllers/$CONFIG_NAME" "conf/scripts/$CONFIG_NAME"

hbot create jino_cross_exchange_arbitrage --controller \
  --name "$CONFIG_NAME" \
  --set exchange_pair_1.connector_name=binance \
  --set exchange_pair_1.trading_pair=BTC-USDT \
  --set exchange_pair_2.connector_name=kucoin \
  --set exchange_pair_2.trading_pair=BTC-USDT \
  --set rate_connector=binance \
  --set quote_conversion_asset=USDT \
  --set safety_mode=observe \
  --set total_amount_quote="$AMOUNT" \
  --set max_trade_amount_quote="$AMOUNT"

echo "Starting Jino OBSERVE-ONLY mode."
echo "No executor/order can be created in this mode."
echo "It only reads market data, balances, network availability/fees and estimates transfer time."

hbot start "$CONFIG_NAME" --controller
