#!/usr/bin/env bash
# OpenLabelServer test entrypoint — run from repository root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "==> Validating Docker Compose configuration"
scripts/validate-compose.sh

echo "==> Validating JSON Schemas against examples"
python3 scripts/validate_schemas.py

echo "==> Validating OpenAPI specification"
python3 scripts/validate_openapi.py

echo "==> Running conformance cases (CN/RS/SS/CS)"
python3 tests/conformance/runner.py

echo
echo "All tests passed."
