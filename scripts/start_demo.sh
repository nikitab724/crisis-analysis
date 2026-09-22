#!/usr/bin/env bash
# Launch the labeled fixture demo on Render or another Python host.
set -euo pipefail

cd "$(dirname "$0")/.."

# This launcher owns its disposable demo directory, independently of live data.
unset CRISIS_DATA_DIR
python proj-dev/app/live_demo/process_test_tweet.py --fixture --output-dir .demo-hosted
export CRISIS_DATA_DIR="$PWD/.demo-hosted"

exec python -m gunicorn \
  --chdir proj-dev/app/live_demo \
  dash_client:server \
  --bind "0.0.0.0:${PORT:-8051}" \
  --workers 1 \
  --threads 2 \
  --access-logfile - \
  --error-logfile -
