"""A consumer crash or lost acknowledgement must not lose or double-count posts."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'proj-dev/app/live_demo'))
import entry  # noqa: E402
from ingest_queue import IngestQueue  # noqa: E402
from pipeline_status import read_status, save_csv  # noqa: E402


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.queue = IngestQueue(self.directory / 'queue.sqlite3')
        self.addCleanup(self.queue.close)
        self.posts = [{'uri': 'at://did:plc:test/app.bsky.feed.post/1', 'text': 'Flood in Austin Texas'}]
        self.queue.append(10, self.posts)
        self.result = {'disasters': ['Flood'], 'locations': ['Austin'], 'city': 'Austin', 'state': 'Texas',
                       'country': 'US', 'polarity': 0, 'latitude': 30.2672, 'longitude': -97.7431}
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def deliver(self, result=None, acknowledgement_error=False, write_error=False):
        work = self.queue.take(20)
        batch = entry.CollectedPosts(work['posts'], work['receipt'], {'state': 'connected'})
        def acknowledge(posts):
            if acknowledgement_error:
                raise requests.Timeout()
            self.assertTrue(self.queue.acknowledge(posts.receipt))
        def save(frame, path):
            if write_error and path.name == 'crisis_counts.csv':
                raise OSError('Simulated count write failure')
            save_csv(frame, path)
        with patch.object(entry, 'get_scraped_posts', return_value=batch), \
                patch.object(entry, 'get_relevance_client', return_value=None), \
                patch.object(entry, 'extract_entities', side_effect=result if isinstance(result, Exception) else None,
                             return_value=self.result if result is None else result), \
                patch.object(entry, 'acknowledge_posts', side_effect=acknowledge), \
                patch.object(entry, 'save_csv', side_effect=save):
            entry.main(output_dir=self.directory)

    def test_lost_ack_replays_without_duplicate_csv_or_totals(self):
        self.deliver(acknowledgement_error=True)
        self.assertEqual(self.queue.status()['queue_depth'], 1)
        self.deliver()
        self.assertEqual(self.queue.status()['queue_depth'], 0)
        self.assertEqual(len(pd.read_csv(self.directory / 'filtered_posts.csv')), 1)
        self.assertEqual(pd.read_csv(self.directory / 'crisis_counts.csv').iloc[0]['count'], 1)
        status = read_status(self.directory)
        self.assertEqual(status['posts_received'], 1)
        self.assertEqual(status['posts_processed'], 1)

    def test_crash_between_csv_writes_rebuilds_counts_before_ack(self):
        self.deliver(write_error=True)
        self.assertEqual(self.queue.status()['queue_depth'], 1)
        self.assertFalse((self.directory / 'crisis_counts.csv').exists())
        self.deliver()
        self.assertEqual(self.queue.status()['queue_depth'], 0)
        self.assertEqual(len(pd.read_csv(self.directory / 'filtered_posts.csv')), 1)
        self.assertEqual(pd.read_csv(self.directory / 'crisis_counts.csv').iloc[0]['disasters'], 'Flood')
        self.assertEqual(pd.read_csv(self.directory / 'crisis_counts.csv').iloc[0]['count'], 1)

    def test_model_failure_keeps_work_until_recovery(self):
        self.deliver(result=requests.Timeout())
        self.assertEqual(self.queue.status()['queue_depth'], 1)
        self.assertEqual(read_status(self.directory)['phase'], 'error')
        self.deliver()
        self.assertEqual(self.queue.status()['queue_depth'], 0)
        self.assertEqual(read_status(self.directory)['posts_received'], 1)
        self.assertEqual(read_status(self.directory)['posts_processed'], 1)

    def test_nonmatching_post_is_acknowledged(self):
        self.deliver(result={'disasters': [], 'locations': [], 'skipped_non_crisis': True})
        self.assertEqual(self.queue.status()['queue_depth'], 0)
        self.assertFalse((self.directory / 'filtered_posts.csv').exists())

    def test_corrupt_existing_csv_is_not_replaced_or_acknowledged(self):
        path = self.directory / 'filtered_posts.csv'
        path.write_text('"unterminated')
        self.deliver()
        self.assertEqual(path.read_text(), '"unterminated')
        self.assertEqual(self.queue.status()['queue_depth'], 1)

    def test_identical_text_from_distinct_uris_is_analyzed_separately(self):
        frame = pd.DataFrame([self.posts[0], {**self.posts[0], 'uri': self.posts[0]['uri']+'2'}])
        with patch.object(entry, 'extract_entities', return_value=self.result) as model, \
                patch.object(entry, 'get_relevance_client', return_value=None):
            result = entry.filter_posts(frame)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(len(result), 2)

    def test_relevance_failure_keeps_batch_queued(self):
        work = self.queue.take(20)
        batch = entry.CollectedPosts(work['posts'], work['receipt'])
        reviewer = Mock()
        reviewer.screen.side_effect = entry.RelevanceUnavailable('Unavailable')
        with patch.object(entry, 'get_scraped_posts', return_value=batch), \
                patch.object(entry, 'get_relevance_client', return_value=reviewer), \
                patch.object(entry, 'extract_entities', return_value=self.result), \
                patch.object(entry, 'acknowledge_posts') as ack:
            entry.main(output_dir=self.directory)
        ack.assert_not_called()
        self.assertEqual(self.queue.status()['queue_depth'], 1)
        self.assertEqual(read_status(self.directory)['phase'], 'error')


if __name__ == '__main__':
    unittest.main()
