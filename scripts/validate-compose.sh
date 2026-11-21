#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=scripts/gates.sh
. "${ROOT}/scripts/gates.sh"

gate_require docker "compose validation"

docker compose -f docker/docker-compose.yml config >/dev/null
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml config >/dev/null
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config >/dev/null

echo "Docker Compose configuration is valid."
