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

    def test_failed_model_requests_are_not_counted_as_analyzed(self):
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.object(entry, "get_scraped_posts", return_value=[{"text": "Flood"}]):
                with patch.object(entry, "extract_entities", side_effect=requests.Timeout):
                    entry.main(output_dir=directory)
            status = read_status(directory)
            self.assertEqual(status["posts_received"], 1)
            self.assertEqual(status["posts_processed"], 0)
            self.assertEqual(status["model_errors"], 1)

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
                    self.assertIn("Updates delayed", str(dashboard.update_activity(0)))
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


if __name__ == "__main__":
    unittest.main()
