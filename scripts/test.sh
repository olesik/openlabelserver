#!/usr/bin/env bash
# OpenLabelServer test entrypoint — run from repository root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=scripts/gates.sh
. "${ROOT}/scripts/gates.sh"

skipped=()

echo "==> Validating Docker Compose configuration"
compose_status=0
scripts/validate-compose.sh || compose_status=$?
if [[ "${compose_status}" -eq "${GATE_SKIPPED}" ]]; then
  skipped+=("compose validation")
elif [[ "${compose_status}" -ne 0 ]]; then
  exit "${compose_status}"
fi

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

echo "==> Testing the font loader, the geometry layer and the PDF/PostScript output backends"
python3 -m pytest -q tests/test_renderer_fonts.py tests/test_renderer_geometry.py tests/test_renderer_output.py

echo "==> Testing the asset registry and raster headers"
python3 -m pytest -q tests/test_renderer_assets.py

echo "==> Testing the barcode encoders and their bars"
python3 -m pytest -q tests/test_renderer_barcode.py

echo "==> Testing the QR code encoder and its grid"
python3 -m pytest -q tests/test_renderer_qrcode.py

echo "==> Testing the PDF417 encoder and its rows"
python3 -m pytest -q tests/test_renderer_pdf417.py

echo "==> Running conformance cases (CN/RS/SS/CS)"
if [ -n "${CONFORMANCE_REPORT:-}" ]; then
  python3 tests/conformance/runner.py --json > "${CONFORMANCE_REPORT}"
else
  python3 tests/conformance/runner.py
fi

echo "==> Checking the conformance job summary renderer"
python3 scripts/conformance_summary.py --check

echo "==> Testing the skipped-gate contract of the check entrypoints"
python3 -m pytest -q tests/test_gate_contract.py

echo
if [[ ${#skipped[@]} -gt 0 ]]; then
  echo "Test steps skipped because a tool is missing:" >&2
  for step in "${skipped[@]}"; do
    echo "  - ${step}" >&2
  done
  echo "Install the missing tools and run this again; those steps were not run." >&2
  exit 1
fi

echo "All tests passed."
