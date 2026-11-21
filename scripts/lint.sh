#!/usr/bin/env bash
# OpenLabelServer lint entrypoint — run from repository root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=scripts/gates.sh
. "${ROOT}/scripts/gates.sh"

skipped=()

# run_gate <what> <script>: run one gate, recording it when its tool is missing.
run_gate() {
  local what="$1"
  local script="$2"
  local status=0

  echo "==> Linting ${what}"
  "${script}" || status=$?
  if [[ "${status}" -eq "${GATE_SKIPPED}" ]]; then
    skipped+=("${script}")
    return 0
  fi
  return "${status}"
}

run_gate "shell scripts" scripts/lint-shell.sh
run_gate "Python scripts" scripts/lint-python.sh
run_gate "YAML files" scripts/lint-yaml.sh
run_gate "Dockerfiles" scripts/lint-docker.sh

if [[ ${#skipped[@]} -gt 0 ]]; then
  echo
  echo "Lint gates skipped because a tool is missing:" >&2
  for gate in "${skipped[@]}"; do
    echo "  - ${gate}" >&2
  done
  echo "Install the missing tools and run this again; those files were not linted." >&2
  exit 1
fi

echo
echo "All lint checks passed."
