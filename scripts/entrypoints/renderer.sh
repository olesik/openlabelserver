#!/usr/bin/env bash
set -euo pipefail

SERVICE="${OLS_SERVICE:-renderer}"
PORT="${OLS_PORT:-8001}"
MODE="${OLS_MODE:-stub}"

if [[ "${MODE}" == "app" ]]; then
  if [[ -f /app/renderer/pyproject.toml || -f /app/renderer/requirements.txt ]]; then
    exec uvicorn renderer.main:app --host 0.0.0.0 --port "${PORT}"
  fi
fi

echo "OpenLabelServer ${SERVICE} running in stub mode (application code not present)."
exec python /app/scripts/stubs/stub_http.py --host 0.0.0.0 --port "${PORT}" --service "${SERVICE}"
