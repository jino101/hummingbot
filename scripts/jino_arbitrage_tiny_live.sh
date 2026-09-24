#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIRM="${JINO_CONFIRM_TINY_LIVE:-}"
AMOUNT="${JINO_LIVE_QUOTE_AMOUNT:-10}"
MAX_RUNTIME="${JINO_LIVE_MAX_SECONDS:-600}"
CONFIG_NAME="conf_jino_tiny_live.yml"

if [[ "$CONFIRM" != "I_UNDERSTAND_LIVE_TRADING" ]]; then
  echo "Refusing live start." >&2
  echo "Set JINO_CONFIRM_TINY_LIVE=I_UNDERSTAND_LIVE_TRADING only when you intentionally want a real-money test." >&2
  exit 10
fi

python - "$AMOUNT" <<'PY'
from decimal import Decimal
import sys
amount = Decimal(sys.argv[1])
if amount <= 0 or amount > Decimal("25"):
    raise SystemExit("JINO_LIVE_QUOTE_AMOUNT must be > 0 and <= 25 USDT for the tiny-live harness")
PY

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
  --set safety_mode=live \
  --set total_amount_quote="$AMOUNT" \
  --set max_trade_amount_quote="$AMOUNT" \
  --set max_daily_loss_quote="$AMOUNT" \
  --set max_completed_trades_per_day=1 \
  --set min_profitability=0.005

echo "About to start REAL trading with a hard per-trade cap of $AMOUNT USDT."
echo "The controller will refuse executor creation unless live-readiness checks pass,"
echo "including connector health, balances, network status, spot-trading permission,"
echo "and withdrawal permission being disabled."

hbot start "$CONFIG_NAME" --controller

cleanup() {
  hbot stop || true
}
trap cleanup EXIT INT TERM

elapsed=0
while (( elapsed < MAX_RUNTIME )); do
  sleep 15
  elapsed=$((elapsed + 15))
  status="$(hbot status)"
  printf '%s\n' "$status"

  # Stop after the first completed trade or immediately on explicit live-readiness failure.
  if printf '%s\n' "$status" | grep -Eq 'completed=1/1|COMPLETED'; then
    echo "Tiny live test observed one completed trade; stopping."
    exit 0
  fi
  if printf '%s\n' "$status" | grep -q 'live_ready=False'; then
    echo "Live-readiness gate is not satisfied; stopping without trading." >&2
    exit 11
  fi
done

echo "Tiny live test window ended without a completed trade; stopping."
