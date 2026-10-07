#!/usr/bin/env bash
# OpenLabelServer lint entrypoint — run from repository root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "==> Linting shell scripts"
scripts/lint-shell.sh

echo "==> Linting Python scripts"
scripts/lint-python.sh

echo "==> Linting YAML files"
scripts/lint-yaml.sh

echo "==> Linting Dockerfiles"
scripts/lint-docker.sh

echo
echo "All lint checks passed."
