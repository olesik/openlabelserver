#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

CONFIG="${ROOT}/scripts/yamllint.yaml"

# shellcheck source=scripts/gates.sh
. "${ROOT}/scripts/gates.sh"

gate_require yamllint "YAML lint"

yamllint -c "${CONFIG}" \
  docker/ \
  specs/ \
  .github/
