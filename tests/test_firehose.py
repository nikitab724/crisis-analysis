"""Continuous collection, cursor recovery, and acknowledged HTTP delivery."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'proj-dev/app/live_demo'))
try:
    import firehose_scraper_server as firehose
except ModuleNotFoundError:
    firehose = None
from ingest_queue import IngestQueue, QueueFull


def post(i):
    return {'uri': f'at://did:plc:sample/app.bsky.feed.post/{i}', 'text': f'post {i}'}


class IngestQueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'queue.sqlite3'
        self.queue = IngestQueue(self.path, capacity=3)
        self.addCleanup(lambda: self.queue.close())

    def test_unacknowledged_work_and_cursor_survive_restart(self):
        self.queue.append(10, [post(1), post(2)])
        first = self.queue.take(1)
        self.queue.close()
        self.queue = IngestQueue(self.path)
        self.assertEqual(self.queue.cursor, 10)
        self.assertEqual(self.queue.take(3), first)
        self.assertTrue(self.queue.acknowledge(first['receipt']))
        self.assertTrue(self.queue.acknowledge(first['receipt']))
        self.assertEqual(self.queue.take(3)['posts'], [post(2)])

    def test_replays_and_duplicate_uris_do_not_add_work(self):
        self.queue.append(10, [post(1)])
        self.queue.append(10, [post(1)])
        self.queue.append(11, [post(1)])
        self.queue.acknowledge(self.queue.take(1)['receipt'])
        self.queue.append(12, [post(1), post(2)])
        self.assertEqual(self.queue.status()['captured'], 2)
        self.assertEqual(self.queue.status()['duplicate_posts'], 2)
        self.assertEqual(self.queue.take(3)['posts'], [post(2)])

    def test_full_queue_rolls_back_whole_commit_and_checkpoint(self):
        self.queue.append(10, [post(1), post(2)])
        with self.assertRaises(QueueFull):
            self.queue.append(11, [post(3), post(4)])
        self.assertEqual(self.queue.cursor, 10)
        self.assertEqual(self.queue.status()['queue_depth'], 2)
        self.queue.acknowledge(self.queue.take(3)['receipt'])
        self.queue.append(11, [post(3), post(4)])
        self.assertEqual(self.queue.cursor, 11)
        self.assertEqual(self.queue.take(3)['posts'], [post(3), post(4)])

    def test_collection_continues_while_consumer_holds_a_batch(self):
        self.queue.append(1, [post(1)])
        batch = self.queue.take(1)
        self.queue.append(2, [post(2)])
        self.queue.append(3, [post(3)])
        self.assertEqual(self.queue.take(3), batch)
        self.assertEqual(self.queue.status()['queue_depth'], 3)
        self.queue.acknowledge(batch['receipt'])
        self.assertEqual(self.queue.take(3)['posts'], [post(2), post(3)])

    def test_source_delay_survives_an_empty_queue_and_restart(self):
        self.queue.append(1, [post(1)], source_time=time.time()-13*3600)
        self.queue.acknowledge(self.queue.take(1)['receipt'])
        self.queue.close()
        self.queue = IngestQueue(self.path)
        self.assertEqual(self.queue.status()['queue_depth'], 0)
        self.assertGreaterEqual(self.queue.status()['source_lag_seconds'], 13*3600)


@unittest.skipIf(firehose is None, 'Requires live collector dependencies')
class FirehoseTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.queue = IngestQueue(Path(self.directory.name) / 'queue.sqlite3')
        self.addCleanup(self.queue.close)
        self.collector = firehose.ContinuousCollector(self.queue)
        self.http = firehose.create_app(self.queue, self.collector).test_client()

    def test_commit_uses_matching_cid_without_network_author_lookup(self):
        records = {'first': {'$type': 'app.bsky.feed.post', 'text': 'Wrong'},
                   'target': {'$type': 'app.bsky.feed.post', 'text': 'Correct'}}
        commit = SimpleNamespace(blocks=b'example', repo='did:plc:sample', ops=[
            SimpleNamespace(action='create', cid='target', path='app.bsky.feed.post/second')])
        with patch.object(firehose.CAR, 'from_bytes', return_value=SimpleNamespace(blocks=records)):
            posts = firehose.commit_posts(commit)
        self.assertEqual(posts[0]['text'], 'Correct')
        self.assertEqual(posts[0]['author'], 'did:plc:sample')
        self.assertTrue(posts[0]['uri'].endswith('/second'))

    def test_http_reads_do_not_open_or_close_the_stream_and_require_ack(self):
        self.queue.append(10, [post(1), post(2)])
        with patch.object(self.collector, 'start') as start, patch.object(self.collector, 'stop') as stop:
            first = self.http.get('/scrape?limit=1').json
            second = self.http.get('/scrape?limit=1').json
            self.assertEqual(first['receipt'], second['receipt'])
            self.assertEqual(first['posts'], second['posts'])
            self.assertEqual(self.http.post('/ack', json={'receipt': first['receipt']}).status_code, 200)
            self.assertEqual(self.http.get('/scrape?limit=1').json['posts'], [post(2)])
        start.assert_not_called()
        stop.assert_not_called()
        self.assertEqual(self.http.get('/scrape?limit=101').status_code, 400)
        self.assertEqual(self.http.post('/ack', json={}).status_code, 400)
        self.assertEqual(self.http.post('/ack', json={'receipt': 'x'*32}).status_code, 409)

    def test_reconnect_uses_committed_cursor(self):
        client = firehose.CheckpointClient(self.collector)
        self.queue.append(42, [post(1)])
        asyncio.run(client._before_connect())
        self.assertEqual(client._params, {'cursor': 42})
        self.queue.append(48, [post(2)])
        asyncio.run(client._before_connect())
        self.assertEqual(client._params, {'cursor': 48})
        self.assertEqual(self.collector.connections, 2)

    def test_sdk_cannot_swallow_bad_record_or_decode_failure(self):
        client = firehose.CheckpointClient(self.collector)
        with patch.object(self.collector, 'handle_message', new=AsyncMock(side_effect=ValueError('bad record'))):
            with self.assertRaises(ValueError):
                asyncio.run(client._process_frame(object()))
        with self.assertRaises(ValueError):
            client._handle_frame_decoding_error(ValueError('bad frame'))
        self.assertIsNone(self.queue.cursor)

    def test_relay_time_is_tracked_and_invalid_or_future_times_are_ignored(self):
        event = SimpleNamespace(seq=10, time='2026-01-01T00:00:00Z')
        with patch.object(firehose, 'parse_subscribe_repos_message', return_value=event):
            asyncio.run(self.collector.handle_message(SimpleNamespace(body={})))
        self.assertGreater(self.queue.status()['source_lag_seconds'], 60)
        for value in [None, 'invalid', '2026-01-01', '2999-01-01T00:00:00Z']:
            self.assertIsNone(firehose.event_timestamp(value))
        self.assertIsNotNone(firehose.event_timestamp(datetime.now(timezone.utc).isoformat()))

    def test_outdated_cursor_and_oversized_commit_are_visible(self):
        for event in [SimpleNamespace(name='OutdatedCursor'), SimpleNamespace(seq=10, too_big=True, ops=[])]:
            with patch.object(firehose, 'parse_subscribe_repos_message', return_value=event):
                asyncio.run(self.collector.handle_message(SimpleNamespace(body={})))
        self.assertEqual(self.queue.status()['gap_events'], 2)
        self.assertEqual(self.queue.cursor, 10)
        self.assertEqual(self.http.get('/health').status_code, 200)
        self.collector.last_event -= 60
        self.assertEqual(self.http.get('/health').status_code, 503)


if __name__ == '__main__':
    unittest.main()
