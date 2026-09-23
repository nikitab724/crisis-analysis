"""Opt-in live stream recovery rehearsal; isolated queue, no NLP calls or published reports."""
import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'proj-dev/app/live_demo'))
from firehose_scraper_server import ContinuousCollector, create_app  # noqa: E402
from ingest_queue import IngestQueue  # noqa: E402


def until(condition, description, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.1)
    raise AssertionError(description)


def main():
    with TemporaryDirectory(prefix='crisis-continuous-check-') as directory:
        path = Path(directory) / 'queue.sqlite3'
        queue = IngestQueue(path)
        collector = ContinuousCollector(queue)
        collector.start()
        try:
            until(lambda: queue.status()['captured'] >= 30, 'No posts collected')
            client = create_app(queue, collector).test_client()
            batch = client.get('/scrape?limit=20').json
            assert len(batch['posts']) == 20
            count = queue.status()['captured']
            connections = collector.connections
            until(lambda: queue.status()['captured'] >= count + 50, 'Collection stopped while processing waited')
            assert client.get('/scrape?limit=20').json['receipt'] == batch['receipt']
            assert collector.connections == connections, 'Normal batches reconnected the stream'
            cursor = queue.cursor
            asyncio.run_coroutine_threadsafe(collector.client.stop(), collector.loop).result(timeout=5)
            until(lambda: collector.connections > connections and queue.cursor > cursor
                  and collector.state == 'connected', 'Reconnect did not recover')
            assert client.get('/scrape?limit=20').json['posts'] == batch['posts']
            before_restart = collector.status()
            print('PASS: collection continued during a held batch; forced reconnect recovered from a checkpoint.', flush=True)
        finally:
            collector.stop()
            queue.close()
        queue = IngestQueue(path)
        collector = ContinuousCollector(queue)
        try:
            assert queue.cursor >= before_restart['cursor']
            assert queue.take(20)['receipt'] == batch['receipt']
            cursor = queue.cursor
            collector.start()
            until(lambda: queue.cursor > cursor, 'Restart did not resume collection')
            assert queue.take(20)['posts'] == batch['posts']
            assert queue.acknowledge(batch['receipt'])
            assert queue.acknowledge(batch['receipt'])
            next_batch = queue.take(20)
            assert not ({p['uri'] for p in batch['posts']} & {p['uri'] for p in next_batch['posts']})
            after_restart = collector.status()
            assert after_restart['gap_events'] == 0, 'Provider reported a coverage gap'
            print('PASS: restart preserved queued posts/cursor; acknowledgement advanced once without duplicate delivery.', flush=True)
            (ROOT / '.demo-hosted/continuous-rehearsal.json').write_text(json.dumps({
                'before_restart': before_restart, 'after_restart': after_restart,
                'held_batch_size': len(batch['posts']), 'synthetic_results_saved': False,
            }, indent=2) + '\n')
        finally:
            collector.stop()
            queue.close()


if __name__ == '__main__':
    main()
