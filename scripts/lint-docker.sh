#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=scripts/gates.sh
. "${ROOT}/scripts/gates.sh"

gate_require hadolint "Dockerfile lint"

mapfile -t dockerfiles < <(find docker -name 'Dockerfile' | sort)

for dockerfile in "${dockerfiles[@]}"; do
  echo "Linting ${dockerfile}..."
  hadolint "${dockerfile}"
done
