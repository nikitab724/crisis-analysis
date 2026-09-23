"""Live activity must distinguish real collection from matching reports."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proj-dev/app/live_demo"))
import dash_client as dashboard  # noqa: E402
import entry  # noqa: E402
from pipeline_status import read_status, save_csv, write_status  # noqa: E402


class PipelineActivityTests(unittest.TestCase):
    def test_activity_shows_counts_without_warning_for_past_errors(self):
        status = {'phase': 'processing', 'posts_received': 10000, 'posts_processed': 9990,
                  'batch_received': 100, 'batch_processed': 76,
                  'model_errors': 3, 'relevance_errors': 40, 'location_errors': 14,
                  'relevance_mode': 'jev', 'collector': {
                      'state': 'connected', 'queue_depth': 10, 'oldest_pending_seconds': 2}}
        with patch.object(dashboard, 'PIPELINE_MODE', 'live'), \
                patch.object(dashboard, 'activity_snapshot', return_value=status), \
                patch.object(dashboard, 'activity_is_stale', return_value=False):
            rendered = str(dashboard.update_activity(0))
            self.assertIn("Strong('10')", rendered)
            self.assertIn('Processing batch', rendered)
            self.assertIn('76 / 100', rendered)
            self.assertNotIn('warning', rendered)
            self.assertNotIn('10000', rendered)
            status['collector']['oldest_pending_seconds'] = 31
            self.assertIn('Analysis is behind', str(dashboard.update_activity(0)))
            status['collector']['oldest_pending_seconds'] = 0
            status['phase'] = 'error'
            status['last_error'] = 'Analysis unavailable. Keeping this batch queued for retry.'
            warning = str(dashboard.update_activity(0))
            self.assertIn('Live updates are temporarily paused', warning)
            self.assertIn('Batch paused', warning)
            self.assertNotIn('Processing batch', warning)
            self.assertNotIn(status['last_error'], warning)
            self.assertNotIn('10000', warning)
            status.update(jev_calls=200, jev_max_calls=200)
            status['collector']['state'] = 'backpressure'
            warning = str(dashboard.update_activity(0))
            self.assertIn('usage limit has been reached', warning)
            self.assertNotIn('catching up', warning)

    def test_nonmatching_batches_still_show_collection_and_analysis(self):
        post = {"text": "A quiet afternoon", "uri": "at://did:plc:sample/app.bsky.feed.post/1"}
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.object(entry, "get_scraped_posts", return_value=[post]):
                with patch.object(entry, "extract_entities", return_value={"disasters": [], "locations": []}):
                    entry.main(output_dir=directory)
                    entry.main(output_dir=directory)
            status = read_status(directory)
            self.assertEqual(status["posts_received"], 2)
            self.assertEqual(status["posts_processed"], 2)
            self.assertEqual(status["matched_records"], 0)
            self.assertEqual(status["batches_completed"], 2)
            self.assertFalse((Path(directory) / "filtered_posts.csv").exists())

    def test_old_source_stream_is_visible_even_when_local_queue_is_empty(self):
        status = {'phase': 'waiting', 'collector': {'state': 'connected', 'queue_depth': 0,
                  'oldest_pending_seconds': 0, 'source_lag_seconds': 13*3600}}
        with patch.object(dashboard, 'PIPELINE_MODE', 'live'), \
                patch.object(dashboard, 'activity_snapshot', return_value=status), \
                patch.object(dashboard, 'activity_is_stale', return_value=False):
            self.assertIn('Live feed is catching up', str(dashboard.update_activity(0)))
            status['collector']['source_lag_seconds'] = 1
            self.assertNotIn('warning', str(dashboard.update_activity(0)))

    def test_failed_model_requests_are_not_counted_as_analyzed(self):
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.object(entry, "get_scraped_posts", return_value=[{"text": "Flood"}]):
                with patch.object(entry, "extract_entities", side_effect=requests.Timeout):
                    entry.main(output_dir=directory)
            status = read_status(directory)
            self.assertEqual(status["posts_received"], 1)
            self.assertEqual(status["posts_processed"], 0)
            self.assertEqual(status["model_errors"], 1)

    def test_fast_rejections_and_stage_timings_are_visible(self):
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.object(entry, 'get_scraped_posts', return_value=[{'text': 'Hello Austin'}]) as collect:
                with patch.object(entry, 'extract_entities', return_value={
                        'disasters': [], 'locations': [], 'skipped_non_crisis': True}):
                    entry.main(output_dir=directory)
            status = read_status(directory)
            collect.assert_called_once_with(20)
            self.assertEqual(status['rule_skipped'], 1)
            self.assertGreaterEqual(status['collection_ms'], 0)
            self.assertGreaterEqual(status['processing_ms'], 0)

    def test_feed_outage_is_visible_and_recovers(self):
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.dict(os.environ, {"CRISIS_PIPELINE_MODE": "live"}):
                with patch.object(entry.requests, "get", side_effect=requests.Timeout):
                    entry.main(output_dir=directory)
            self.assertEqual(read_status(directory)["phase"], "error")
            with patch.object(entry, "get_scraped_posts", return_value=[]):
                entry.main(output_dir=directory)
            self.assertEqual(read_status(directory)["phase"], "waiting")
            self.assertIsNone(read_status(directory)["last_error"])

    def test_stalled_live_activity_is_not_reported_as_healthy(self):
        with TemporaryDirectory() as directory:
            for name in ("filtered_posts.csv", "crisis_counts.csv"):
                (Path(directory) / name).touch()
            (Path(directory) / "pipeline_status.json").write_text(json.dumps({
                "phase": "processing", "updated_at": "2020-01-01T00:00:00+00:00"}))
            response = Mock(status_code=200)
            response.json.return_value = {"status": "healthy"}
            with patch.object(dashboard, "DATA_DIR", Path(directory)), patch.object(dashboard, "PIPELINE_MODE", "live"):
                with patch.object(dashboard.backend_http, "get", return_value=response):
                    self.assertEqual(dashboard.server.test_client().get("/health").status_code, 503)
                    self.assertIn("Live updates are delayed", str(dashboard.update_activity(0)))
                    write_status(directory, phase="collecting")
                    self.assertEqual(dashboard.server.test_client().get("/health").status_code, 200)

    def test_failed_csv_write_preserves_previous_snapshot(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text("previous complete data\n")
            broken_frame = Mock()
            def broken_write(temporary, **_kwargs):
                temporary.write_text("incomplete")
                raise OSError("disk failure")
            broken_frame.to_csv.side_effect = broken_write
            with self.assertRaises(OSError):
                save_csv(broken_frame, path)
            self.assertEqual(path.read_text(), "previous complete data\n")

    def test_backlog_and_known_gaps_are_visible_even_while_analysis_runs(self):
        with TemporaryDirectory() as directory:
            write_status(directory, phase='processing', collector={
                'state': 'connected', 'queue_depth': 42, 'oldest_pending_seconds': 8, 'gap_events': 1})
            with patch.object(dashboard, 'DATA_DIR', Path(directory)), patch.object(dashboard, 'PIPELINE_MODE', 'live'), \
                    patch.dict(os.environ, {'SCRAPER_SERVER_URL': ''}):
                rendered = str(dashboard.update_activity(0))
                self.assertIn("Strong('42')", rendered)
                self.assertNotIn('Stream connected', rendered)
                self.assertIn('Some earlier posts could not be recovered', rendered)

    def test_collector_outage_is_visible_with_a_fresh_processor_snapshot(self):
        with TemporaryDirectory() as directory:
            write_status(directory, phase='processing', collector={'state': 'connected', 'queue_depth': 3})
            with patch.object(dashboard, 'DATA_DIR', Path(directory)), patch.object(dashboard, 'PIPELINE_MODE', 'live'), \
                    patch.dict(os.environ, {'SCRAPER_SERVER_URL': 'http://127.0.0.1:5004'}), \
                    patch.object(dashboard.backend_http, 'get', side_effect=requests.Timeout):
                snapshot = dashboard.activity_snapshot()
                self.assertEqual(snapshot['collector']['state'], 'unavailable')
                self.assertEqual(snapshot['collector']['queue_depth'], 3)
                self.assertIn('Live feed disconnected. Reconnecting.', str(dashboard.update_activity(0)))
                self.assertNotIn("Strong('3')", str(dashboard.update_activity(0)))

    def test_large_counts_and_unknown_stale_or_idle_batch_states(self):
        status = {'phase': 'processing', 'batch_received': 100, 'batch_processed': 105,
                  'collector': {'state': 'connected', 'queue_depth': 25432}}
        with patch.object(dashboard, 'PIPELINE_MODE', 'live'), \
                patch.object(dashboard, 'activity_snapshot', return_value=status), \
                patch.object(dashboard, 'activity_is_stale', return_value=False) as stale:
            rendered = str(dashboard.update_activity(0))
            self.assertIn('25,432', rendered)
            self.assertIn('100 / 100', rendered)
            self.assertNotIn('105 / 100', rendered)
            stale.return_value = True
            rendered = str(dashboard.update_activity(0))
            self.assertNotIn('Processing batch', rendered)
            self.assertNotIn('100 / 100', rendered)
            self.assertIn('delayed', rendered)
            stale.return_value = False
            status['phase'] = 'waiting'
            self.assertIn('Idle', str(dashboard.update_activity(0)))
            status['collector']['queue_depth'] = None
            self.assertNotIn('25,432', str(dashboard.update_activity(0)))

    def test_sample_modes_do_not_claim_to_have_a_live_queue(self):
        for mode in ('fixture', 'demo', ''):
            with self.subTest(mode=mode), patch.object(dashboard, 'PIPELINE_MODE', mode):
                self.assertIsNone(dashboard.update_activity(0))

    def test_processed_total_uses_completed_queue_posts_not_attempts_or_matches(self):
        status = {'phase': 'processing', 'posts_processed': 999999, 'matched_records': 665,
                  'batch_received': 100, 'batch_processed': 76,
                  'collector': {'state': 'connected', 'acknowledged': 815703, 'queue_depth': 57154}}
        with patch.object(dashboard, 'PIPELINE_MODE', 'live'), \
                patch.object(dashboard, 'activity_snapshot', return_value=status), \
                patch.object(dashboard, 'activity_is_stale', return_value=False):
            rendered = str(dashboard.update_activity(0))
            self.assertIn('Processed ', rendered)
            self.assertIn('815,703', rendered)
            self.assertIn('57,154', rendered)
            self.assertIn('76 / 100', rendered)
            self.assertNotIn('999,999', rendered)
            status.update(phase='error', batch_processed=0)
            self.assertIn('815,703', str(dashboard.update_activity(0)))
            status['collector']['acknowledged'] += 100
            self.assertIn('815,803', str(dashboard.update_activity(0)))
            status['collector']['state'] = 'unavailable'
            self.assertNotIn('815,803', str(dashboard.update_activity(0)))


if __name__ == "__main__":
    unittest.main()
