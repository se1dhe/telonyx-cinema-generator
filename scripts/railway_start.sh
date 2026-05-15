#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH=${PYTHONPATH:-/app/src}
export PORT=${PORT:-8080}
export STORAGE_DIR=${STORAGE_DIR:-/data/storage}

mkdir -p "$STORAGE_DIR"

echo "Starting TELONYX Cinema Generator"
echo "PYTHONPATH=$PYTHONPATH"
echo "PORT=$PORT"
echo "STORAGE_DIR=$STORAGE_DIR"

echo "Running preflight..."
python -m telonyx_cinema.maintenance.preflight || true

echo "Starting worker in background..."
python -m telonyx_cinema.worker.main &
WORKER_PID=$!

echo "Starting API..."
uvicorn telonyx_cinema.api.main:app --host 0.0.0.0 --port "$PORT" &
API_PID=$!

trap 'echo "Stopping services..."; kill $WORKER_PID $API_PID 2>/dev/null || true; wait || true' SIGTERM SIGINT

wait -n $WORKER_PID $API_PID
EXIT_CODE=$?

echo "One process exited with code $EXIT_CODE. Stopping the other process..."
kill $WORKER_PID $API_PID 2>/dev/null || true
wait || true
exit $EXIT_CODE
