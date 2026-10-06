#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== Jino safe observe stack ==="
echo "1/2 Starting credential-free market observer..."
bash scripts/jino_arbitrage_observe.sh

echo "2/2 Starting mobile dashboard..."
echo "Leave this terminal running while you use the dashboard/app."
exec bash scripts/jino_dashboard.sh
