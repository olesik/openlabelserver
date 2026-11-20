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

echo "==> Validating API examples against the OpenAPI contract"
python3 scripts/validate_examples.py

echo "==> Testing the example validator"
python3 -m pytest -q tests/test_validate_examples.py

echo "==> Testing the RenderSpec parser, coordinate, layout, clipping, binding, composition and object renderers"
python3 -m pytest -q tests/test_renderer_renderspec.py tests/test_renderer_coordinates.py tests/test_renderer_layout.py tests/test_renderer_clip.py tests/test_renderer_binding.py tests/test_renderer_composition.py tests/test_renderer_objects.py

echo "==> Testing the geometry layer and the PDF/PostScript output backends"
python3 -m pytest -q tests/test_renderer_geometry.py tests/test_renderer_output.py

echo "==> Running conformance cases (CN/RS/SS/CS)"
if [ -n "${CONFORMANCE_REPORT:-}" ]; then
  python3 tests/conformance/runner.py --json > "${CONFORMANCE_REPORT}"
else
  python3 tests/conformance/runner.py
fi

echo "==> Checking the conformance job summary renderer"
python3 scripts/conformance_summary.py --check

echo
echo "All tests passed."
