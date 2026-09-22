#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install -r requirements-live.txt
# Render uses Linux CPUs; avoid installing the much larger CUDA runtime.
if [[ "$(uname -s)" == "Linux" ]]; then
  python -m pip install 'torch==2.14.0' --index-url https://download.pytorch.org/whl/cpu
else
  python -m pip install 'torch==2.14.0'
fi
python -m spacy download en_core_web_trf-3.8.0 --direct
python build_disaster_model.py
python tests/check_disaster_model.py
