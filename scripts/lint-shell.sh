#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

mapfile -t scripts < <(find scripts -type f \( -name '*.sh' \) ! -path '*/stubs/*' | sort)

if [[ ${#scripts[@]} -eq 0 ]]; then
  echo "No shell scripts found."
  exit 0
fi

shellcheck "${scripts[@]}"
