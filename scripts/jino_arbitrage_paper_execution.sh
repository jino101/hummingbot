#!/usr/bin/env bash
set -euo pipefail

CONFIG_NAME="conf_jino_paper_execution.yml"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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

rm -f "conf/controllers/$CONFIG_NAME" "conf/scripts/$CONFIG_NAME" "logs/logs_${CONFIG_NAME%.yml}.log"

hbot create jino_cross_exchange_arbitrage --controller   --name "$CONFIG_NAME"   --set exchange_pair_1.connector_name=binance_paper_trade   --set exchange_pair_1.trading_pair=BTC-USDT   --set exchange_pair_2.connector_name=kucoin_paper_trade   --set exchange_pair_2.trading_pair=BTC-USDT   --set rate_connector=binance_paper_trade   --set quote_conversion_asset=USDT   --set safety_mode=paper   --set total_amount_quote=5   --set max_trade_amount_quote=5   --set max_daily_loss_quote=5   --set max_completed_trades_per_day=1   --set min_profitability=0.005   --set paper_test_force_execution=true

echo "Starting deterministic paper execution-path test..."
hbot start "$CONFIG_NAME" --controller

success=0
for _ in $(seq 1 24); do
  sleep 5
  status="$(hbot status)"
  printf '%s
' "$status"

  if printf '%s
' "$status" | grep -Eq 'COMPLETED|Volume Traded[[:space:]]*[1-9]|completed=1/1'; then
    success=1
    break
  fi

  if hbot logs -n 500 | grep -E ' - (ERROR|CRITICAL) - ' >/tmp/jino_execution_errors.txt; then
    cat /tmp/jino_execution_errors.txt
    hbot stop || true
    echo "Execution-path test hit a runtime error." >&2
    exit 2
  fi
done

echo "Stopping deterministic paper execution-path test..."
hbot stop || true

if [[ "$success" -ne 1 ]]; then
  echo "No completed paper execution was observed within 120 seconds." >&2
  exit 3
fi

echo "Jino paper execution-path test observed a completed paper trade."
