#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=scripts/gates.sh
. "${ROOT}/scripts/gates.sh"

gate_require ruff "Python lint"

ruff check --config scripts/ruff.toml scripts/
