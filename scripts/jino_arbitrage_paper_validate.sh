#!/usr/bin/env bash
set -euo pipefail

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

echo "== 1/3 Targeted regression tests =="
PYTHONPATH="$ROOT_DIR" pytest -q \
  test/controllers/generic/test_jino_cross_exchange_arbitrage.py \
  test/hummingbot/jino_arbitrage \
  test/hummingbot/data_feed/test_market_data_provider.py \
  test/hummingbot/cli/test_strategy_configs.py \
  test/hummingbot/strategy/test_jino_strategy_v2_loader.py \
  test/hummingbot/strategy_v2/executors/arbitrage_executor/test_arbitrage_executor.py

echo "== 2/3 Five-minute paper soak =="
JINO_SOAK_SECONDS="${JINO_SOAK_SECONDS:-300}" \
JINO_SOAK_STATUS_INTERVAL="${JINO_SOAK_STATUS_INTERVAL:-30}" \
bash scripts/jino_arbitrage_paper_soak.sh

echo "== 3/3 Deterministic full paper execution path =="
bash scripts/jino_arbitrage_paper_execution.sh

echo "Jino full paper validation passed: tests + soak + completed paper execution."
