#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

CONFIG="${ROOT}/scripts/yamllint.yaml"

if ! command -v yamllint >/dev/null 2>&1; then
  echo "yamllint not installed; skipping YAML lint."
  exit 0
fi

yamllint -c "${CONFIG}" \
  docker/ \
  specs/ \
  .github/
