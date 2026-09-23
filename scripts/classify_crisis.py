#!/usr/bin/env python3
"""Classify one post with Jev, without writing reports or requiring the NLP server."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'proj-dev/app/live_demo'))
from jev_relevance import JevRelevance, RelevanceUnavailable  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text', required=True, help='Post to classify; sends one API request')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    try:
        client = JevRelevance(os.environ.get('AI_GATEWAY_API_KEY'), max_calls=1,
                              threshold=float(os.environ.get('JEV_MIN_PROBABILITY', '.8')))
        started = time.perf_counter()
        result = client.classify_text(args.text)
    except (ValueError, RelevanceUnavailable) as exc:
        parser.exit(1, f'Classification unavailable: {exc}\n')
    print(json.dumps({**result, 'elapsed_ms': round((time.perf_counter() - started) * 1000)}, indent=2))


if __name__ == '__main__':
    main()
