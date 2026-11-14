#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v hadolint >/dev/null 2>&1; then
  echo "hadolint not installed; skipping Dockerfile lint."
  exit 0
fi

mapfile -t dockerfiles < <(find docker -name 'Dockerfile' | sort)

for dockerfile in "${dockerfiles[@]}"; do
  echo "Linting ${dockerfile}..."
  hadolint "${dockerfile}"
done
