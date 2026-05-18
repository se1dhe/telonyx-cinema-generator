#!/usr/bin/env bash
set -euo pipefail

mkdir -p .data/storage
docker compose up --build
