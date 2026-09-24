#!/usr/bin/env bash
# Launch the independent sample replay, or an explicitly configured live gateway.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "${CRISIS_PIPELINE_MODE:-}" != "sample" && -n "${LIVE_DASHBOARD_URL:-}" ]]; then
  app_dir="scripts"
  app_target="dashboard_proxy:create_app()"
  app_threads=4
else
  # Sample replay is read-only and has no backend, credentials, or generated CSVs.
  export CRISIS_PIPELINE_MODE=sample
  app_dir="proj-dev/app/live_demo"
  app_target="dash_client:server"
  app_threads=2
fi

exec python -m gunicorn \
  --chdir "$app_dir" \
  "$app_target" \
  --bind "0.0.0.0:${PORT:-8051}" \
  --workers 1 \
  --threads "$app_threads" \
  --timeout 60 \
  --access-logfile - \
  --error-logfile -
