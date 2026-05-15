#!/usr/bin/env bash
set -euo pipefail

mkdir -p .data/storage

echo "TELONYX Cinema Generator local stack"
echo "Building and starting API, Worker and Redis..."

docker compose up --build
