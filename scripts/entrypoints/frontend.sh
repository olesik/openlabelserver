#!/usr/bin/env bash
set -euo pipefail

SERVICE="${OLS_SERVICE:-frontend}"
PORT="${OLS_PORT:-5173}"
MODE="${OLS_MODE:-stub}"

if [[ "${MODE}" == "app" && -f /app/frontend/dist/index.html ]]; then
  exec serve -s /app/frontend/dist -l "${PORT}"
fi

if [[ "${MODE}" == "app" && -f /app/frontend/package.json ]]; then
  cd /app/frontend
  exec npm run dev -- --host 0.0.0.0 --port "${PORT}"
fi

echo "OpenLabelServer ${SERVICE} running in stub mode (application code not present)."
exec python3 /app/scripts/stubs/stub_http.py --host 0.0.0.0 --port "${PORT}" --service "${SERVICE}"
