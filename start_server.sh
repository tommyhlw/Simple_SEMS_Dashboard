#!/usr/bin/env bash
set -euo pipefail

# start_server.sh [ENV_FILE] [PORT]
# Loads environment variables from ENV_FILE (default: .env), activates .venv if present
# and starts the FastAPI app via uvicorn on given PORT (default: 8000).

ENV_FILE="./.env"
PORT="8000"

if [ "$#" -ge 1 ] && [ -n "$1" ]; then
  ENV_FILE="$1"
fi
if [ "$#" -ge 2 ] && [ -n "$2" ]; then
  PORT="$2"
fi

if [ -f "$ENV_FILE" ]; then
  echo "Loading environment from $ENV_FILE"
  # Parse .env safely: ignore comments, blank lines, and only KEY=VALUE pairs.
  set -a; source .env; set +a
else
  echo "No env file found at $ENV_FILE — proceeding with current environment variables"
fi

# Use virtualenv python/uvicorn if available
if [ -x ".venv/bin/uvicorn" ]; then
  UVICORN_BIN=".venv/bin/uvicorn"
elif command -v uvicorn >/dev/null 2>&1; then
  UVICORN_BIN="$(command -v uvicorn)"
else
  echo "uvicorn not found. Install dependencies: pip install -r requirements.txt" >&2
  exit 1
fi

export PYTHONUNBUFFERED=1
echo "Starting FastAPI on port $PORT using $UVICORN_BIN"
exec "$UVICORN_BIN" api.main:app --host 0.0.0.0 --port "$PORT" --reload --log-level info
