#!/usr/bin/env bash
# Validate published JSON Schemas against example documents.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

python3 scripts/validate_schemas.py "$@"
