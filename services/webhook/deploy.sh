#!/bin/sh
set -eu

repo="${1:-unknown}"
sha="${2:-unknown}"
ref="${3:-unknown}"

ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }

echo "[$(ts)] deploy start: repo=$repo sha=$sha ref=$ref"

cd "$PROJECT_DIR"

docker compose -f compose.staging.yml -f compose.traefik.yml pull
docker compose -f compose.staging.yml -f compose.traefik.yml up -d
docker image prune -f

echo "[$(ts)] deploy done: repo=$repo sha=$sha ref=$ref"
