#!/usr/bin/env bash
set -euo pipefail

SERVICE="${OLS_SERVICE:-printing}"
PORT="${OLS_PORT:-8002}"
MODE="${OLS_MODE:-stub}"

if [[ "${MODE}" == "app" ]]; then
  if [[ -f /app/printing/pyproject.toml || -f /app/printing/requirements.txt ]]; then
    exec uvicorn printing.main:app --host 0.0.0.0 --port "${PORT}"
  fi
fi

echo "OpenLabelServer ${SERVICE} running in stub mode (application code not present)."
exec python /app/scripts/stubs/stub_http.py --host 0.0.0.0 --port "${PORT}" --service "${SERVICE}"
