#!/usr/bin/env bash
set -euo pipefail

CONFIG_NAME="conf_jino_paper_soak.yml"
DURATION_SECONDS="${JINO_SOAK_SECONDS:-300}"
STATUS_INTERVAL="${JINO_SOAK_STATUS_INTERVAL:-30}"
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

cleanup() {
  if hbot status --json 2>/dev/null | grep -q '"running": true'; then
    echo "Stopping Jino paper soak test..."
    hbot stop || true
  fi
}
trap cleanup EXIT INT TERM

SOAK_NAME="${CONFIG_NAME%.yml}"

# This helper deliberately reuses one dedicated bot name. Hummingbot appends to
# logs/logs_<name>.log across runs, so stale ERROR lines from an older failed
# attempt would otherwise make a healthy soak test look broken.
rm -f "conf/controllers/$CONFIG_NAME" \
      "conf/scripts/$CONFIG_NAME" \
      "logs/logs_${SOAK_NAME}.log"

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

echo "---- current-run log errors ----"
errors="$(hbot logs -n 2000 | grep -E ' - (ERROR|CRITICAL) - ' || true)"
if [[ -n "$errors" ]]; then
  printf '%s\n' "$errors"
  echo "Jino paper soak test detected ERROR/CRITICAL entries from THIS run." >&2
  exit 2
fi

echo "Jino paper soak test completed without ERROR/CRITICAL log entries from this run."
