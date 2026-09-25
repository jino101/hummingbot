#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${JINO_DASHBOARD_HOST:-0.0.0.0}"
PORT="${JINO_DASHBOARD_PORT:-8787}"

if [[ "${CONDA_DEFAULT_ENV:-}" != "hummingbot" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "conda is not available; activate the hummingbot environment first." >&2
    exit 1
  fi
  exec conda run --no-capture-output -n hummingbot bash "$0" "$@"
fi

PYTHONPATH="$ROOT_DIR" python jino_mobile/server.py --host "$HOST" --port "$PORT"
