#!/usr/bin/env bash
# Launch a configured live-dashboard gateway, or the independent fixture demo.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -n "${LIVE_DASHBOARD_URL:-}" ]]; then
  app_dir="scripts"
  app_target="dashboard_proxy:create_app()"
  app_threads=4
else
  # This launcher owns its disposable fixture directory, independently of live data.
  unset CRISIS_DATA_DIR
  python proj-dev/app/live_demo/process_test_tweet.py --fixture --output-dir .demo-hosted
  export CRISIS_DATA_DIR="$PWD/.demo-hosted"
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
  --access-logfile - \
  --error-logfile -
