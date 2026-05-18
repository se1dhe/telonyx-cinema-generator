#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-/app/src}"
export PORT="${PORT:-8080}"
export STORAGE_DIR="${STORAGE_DIR:-/data/storage}"

mkdir -p "$STORAGE_DIR"

echo "Starting TELONYX Cinema Finalizer"
echo "PORT=$PORT"
echo "STORAGE_DIR=$STORAGE_DIR"
echo "ENABLE_WHISPER=${ENABLE_WHISPER:-true}"
echo "WHISPER_MODEL=${WHISPER_MODEL:-small}"

python - <<'PY'
import importlib
importlib.import_module("telonyx_cinema.api.main")
print("import_ok=telonyx_cinema.api.main")
PY

exec uvicorn telonyx_cinema.api.main:app --host 0.0.0.0 --port "$PORT"
