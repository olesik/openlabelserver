#!/usr/bin/env bash
# CI container entrypoint — dispatches to lint or test scripts.
set -euo pipefail

ROOT="/workspace"
cd "${ROOT}"

case "${1:-test}" in
  lint)
    exec "${ROOT}/scripts/lint.sh"
    ;;
  test)
    exec "${ROOT}/scripts/test.sh"
    ;;
  *)
    exec "$@"
    ;;
esac
