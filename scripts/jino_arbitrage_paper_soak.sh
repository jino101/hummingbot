#!/usr/bin/env bash
set -euo pipefail

CONFIG_NAME="conf_jino_paper_soak.yml"
DURATION_SECONDS="${JINO_SOAK_SECONDS:-300}"
STATUS_INTERVAL="${JINO_SOAK_STATUS_INTERVAL:-30}"
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

cleanup() {
  if hbot status --json 2>/dev/null | grep -q '"running": true'; then
    echo "Stopping Jino paper soak test..."
    hbot stop || true
  fi
}
trap cleanup EXIT INT TERM

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
  --set max_daily_loss_quote=25 \
  --set max_completed_trades_per_day=100 \
  --set min_profitability=0.005

echo "Starting Jino paper soak test for ${DURATION_SECONDS}s..."
hbot start "$CONFIG_NAME" --controller

start_ts="$(date +%s)"
while true; do
  now="$(date +%s)"
  elapsed=$((now - start_ts))
  if (( elapsed >= DURATION_SECONDS )); then
    break
  fi

  echo "---- status at ${elapsed}s ----"
  hbot status
  sleep "$STATUS_INTERVAL"
done

echo "---- final status ----"
hbot status

echo "---- recent log errors ----"
errors="$(hbot logs -n 600 | grep -E ' - (ERROR|CRITICAL) - ' || true)"
if [[ -n "$errors" ]]; then
  echo "$errors"
  echo "Jino paper soak test detected runtime errors." >&2
  exit 2
fi

echo "Jino paper soak test completed without ERROR/CRITICAL log entries."
