#!/usr/bin/env bash
set -euo pipefail

CONFIG_NAME="conf_jino_paper_execution.yml"
TEST_QUOTE_AMOUNT="${JINO_EXECUTION_QUOTE_AMOUNT:-25}"
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

hbot create jino_cross_exchange_arbitrage --controller   --name "$CONFIG_NAME"   --set exchange_pair_1.connector_name=binance_paper_trade   --set exchange_pair_1.trading_pair=BTC-USDT   --set exchange_pair_2.connector_name=kucoin_paper_trade   --set exchange_pair_2.trading_pair=BTC-USDT   --set rate_connector=binance_paper_trade   --set quote_conversion_asset=USDT   --set safety_mode=paper   --set total_amount_quote="$TEST_QUOTE_AMOUNT"   --set max_trade_amount_quote="$TEST_QUOTE_AMOUNT"   --set max_daily_loss_quote="$TEST_QUOTE_AMOUNT"   --set max_completed_trades_per_day=1   --set min_profitability=0.005   --set paper_test_force_execution=true

echo "Starting deterministic paper execution-path test with ${TEST_QUOTE_AMOUNT} USDT paper notional..."

start_output=""
if start_output="$(hbot start "$CONFIG_NAME" --controller 2>&1)"; then
  printf '%s\n' "$start_output"
else
  start_rc=$?
  printf '%s\n' "$start_output" >&2
  if [[ "$start_output" == *"invalid password"* && -t 0 ]]; then
    echo "The cached Hummingbot password is invalid. Please enter the real local keystore password." >&2
    unset HBOT_PASSWORD CONFIG_PASSWORD
    read -r -s -p "Hummingbot password (retry): " HBOT_PASSWORD
    echo
    export HBOT_PASSWORD
    hbot start "$CONFIG_NAME" --controller
  else
    exit "$start_rc"
  fi
fi

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

  recent_logs="$(hbot logs -n 200)"
  if printf '%s\n' "$recent_logs" | grep -E ' - (ERROR|CRITICAL) - ' >/tmp/jino_execution_errors.txt; then
    echo "---- ERROR/CRITICAL entries ----"
    cat /tmp/jino_execution_errors.txt
    echo "---- recent log context ----"
    printf '%s\n' "$recent_logs"
    hbot stop || true
    echo "Execution-path test hit a runtime error. Full recent context printed above." >&2
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
