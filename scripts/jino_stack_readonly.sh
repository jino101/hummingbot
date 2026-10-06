#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== Jino authenticated read-only stack ==="
echo "This requires already-configured READ-ONLY Binance and KuCoin API keys."
echo "Trading permission OFF. Withdrawals OFF."
echo "1/2 Starting authenticated read-only observer..."
bash scripts/jino_arbitrage_readonly.sh

echo "2/2 Starting mobile dashboard..."
echo "Leave this terminal running while you use the dashboard/app."
exec bash scripts/jino_dashboard.sh
