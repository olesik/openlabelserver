#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v ruff >/dev/null 2>&1; then
  echo "ruff not installed; skipping Python lint."
  exit 0
fi

ruff check --config scripts/ruff.toml scripts/
