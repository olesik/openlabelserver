#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not available; skipping compose validation."
  exit 0
fi

docker compose -f docker/docker-compose.yml config >/dev/null
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml config >/dev/null
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config >/dev/null

echo "Docker Compose configuration is valid."
