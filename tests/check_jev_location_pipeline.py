"""Opt-in real NLP → gazetteer → Jev → processor smoke test; no posts are saved.

Requires a running model service and a Gateway key. At most 12 Gateway calls.
"""

import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from dotenv import load_dotenv
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
sys.path.insert(0, str(ROOT / 'proj-dev/app/live_demo'))
import entry  # noqa: E402
from jev_relevance import JevRelevance  # noqa: E402

CASES = [
    ('river-context', 'Flood in Portland along the Willamette River. Streets are underwater.', 'Oregon', True),
    ('bay-context', 'Flood in Portland along Casco Bay. Waterfront businesses evacuated.', 'Maine', True),
    ('bare-name', 'Flood in Portland. Streets are underwater.', None, False),
    ('explicit-state', 'Flood in Austin Texas. Streets are underwater and evacuations are underway.', 'Texas', False),
    ('foreign-place', 'Flood in Portland, Victoria, Australia. Streets are underwater.', None, False),
    ('metaphor', 'Flood of compliments in Portland near Casco Bay after the new album launch.', None, False),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Running model service, e.g. http://127.0.0.1:5002')
    args = parser.parse_args()
    client = JevRelevance(os.environ.get('AI_GATEWAY_API_KEY'), max_calls=12)
    results = []
    with patch.object(entry, 'MODEL_SERVER_URL', args.url.rstrip('/')), \
            patch.object(entry, 'get_relevance_client', return_value=client):
        for name, text, expected_state, chosen in CASES:
            stats = {}
            progress = []
            frame = entry.filter_posts(pd.DataFrame([{'text': text, 'created_at': '2026-09-22T12:00:00Z'}]),
                                       on_progress=lambda _count, errors: progress.append(errors),
                                       relevance_stats=stats)
            actual_states = list(frame['state'])
            passed = actual_states == ([expected_state] if expected_state else [])
            if expected_state:
                passed = passed and frame.iloc[0]['relevance_status'] == 'passed' and frame.iloc[0]['country'] == 'US'
                if chosen:
                    passed = passed and frame.iloc[0]['location_model'] == 'typesafe-ai/jev'
            passed = passed and not stats.get('location_errors') and not stats.get('relevance_errors')
            passed = passed and not any(progress)
            results.append({'case': name, 'passed': bool(passed), 'states': actual_states, 'stats': stats})
            print(f"{'PASS' if passed else 'FAIL'}: {name}; states={actual_states}", flush=True)
    output = ROOT / '.demo-hosted/jev-location-pipeline.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({'calls': client.calls, 'results': results}, indent=2) + '\n')
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
