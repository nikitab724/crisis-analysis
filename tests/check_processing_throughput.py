"""Controlled burst benchmark with delayed model/network substitutes; no paid API calls."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
from unittest.mock import Mock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'proj-dev/app/live_demo'))
import entry  # noqa: E402
from ingest_queue import IngestQueue  # noqa: E402
from jev_relevance import JevRelevance  # noqa: E402


def run(workers, size, prefilter, total=1000):
    inference = threading.Lock()
    calls = 0
    def model(text):
        nonlocal calls
        calls += 1
        time.sleep(.001)  # Per-request transport/dispatch overhead.
        if not text.startswith('Flood'):
            return {'disasters': [], 'locations': [], 'skipped_non_crisis': True}
        with inference:
            time.sleep(.005)  # One shared transformer; never duplicated or parallel.
        time.sleep(.015)  # Read-only location lookup can overlap.
        return {'disasters': ['Flood'], 'locations': ['Austin'], 'city': 'Austin', 'state': 'Texas',
                'country': 'US', 'polarity': 0, 'latitude': 30.2672, 'longitude': -97.7431}
    def review(*args, **kwargs):
        time.sleep(.03)
        return Mock(status_code=200, json=lambda: {'answers': {
            'candidate_0': {'type': 'boolean', 'probability': .95}}})
    reviewer = JevRelevance('test-only', max_calls=1000, session=Mock(post=Mock(side_effect=review)))
    rows = [{'uri': f'at://did:plc:benchmark/app.bsky.feed.post/{i}',
             'text': f'{"Flood in Austin Texas" if i % 20 == 0 else "Ordinary conversation"} {i}'}
            for i in range(total)]
    saved = []
    with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
        queue = IngestQueue(Path(directory) / 'queue.sqlite3')
        try:
            queue.append(1, rows)
            start = time.perf_counter()
            with patch.object(entry, 'extract_entities', side_effect=model), \
                    patch.object(entry, 'screen_candidates', side_effect=lambda texts: [text.startswith('Flood') for text in texts]), \
                    patch.object(entry, 'get_relevance_client', return_value=reviewer):
                while work := queue.take(size)['posts']:
                    receipt = queue.take(size)['receipt']
                    result = entry.filter_posts(pd.DataFrame(work), workers=workers, prefilter=prefilter)
                    saved.extend(result.to_dict('records'))
                    assert queue.acknowledge(receipt)
                    if workers == 1:
                        time.sleep(.1)  # Former pause after every full batch.
            elapsed = time.perf_counter() - start
            status = queue.status()
            assert status['acknowledged'] == total and status['queue_depth'] == 0
        finally:
            queue.close()
    return {'posts': total, 'seconds': round(elapsed, 3), 'posts_per_second': round(total / elapsed, 1),
            'model_requests': calls, 'jev_requests': reviewer.calls, 'matched_records': len(saved)}, saved


def main():
    before, original = run(1, 20, False)
    after, optimized = run(4, 100, True)
    assert json.dumps(original, sort_keys=True) == json.dumps(optimized, sort_keys=True)
    assert before['jev_requests'] == after['jev_requests'] == before['matched_records'] == after['matched_records']
    result = {'kind': 'controlled delayed-service benchmark, not a live throughput guarantee',
              'sequential': before, 'concurrent': after,
              'speedup': round(before['seconds'] / after['seconds'], 2), 'same_results': True}
    output = ROOT / '.demo-hosted/processing-benchmark.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
