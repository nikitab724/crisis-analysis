"""Regression checks for the repeatable demo and targeted cleanup fixes."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proj-dev/app/live_demo"))
import entry  # noqa: E402
import process_test_tweet as demo  # noqa: E402
import dash_client as dashboard  # noqa: E402


class DemoPipelineTests(unittest.TestCase):
    def setUp(self):
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_repeatable_http_injection_and_dashboard(self):
        original_scraper = entry.get_scraped_posts
        original_url = entry.MODEL_SERVER_URL
        with TemporaryDirectory() as directory:
            destination = Path(directory)
            posts, counts = demo.process_test_tweet(fixture=True, output_dir=destination)
            self.assertEqual(posts.iloc[0]["text"], demo.DEFAULT_TEXT)
            self.assertEqual(counts.iloc[0]["count"], 1)
            self.assertEqual(counts.iloc[0]["severity"], 0)
            first = [(destination / name).read_bytes() for name in demo.OUTPUT_FILES]
            demo.process_test_tweet(fixture=True, output_dir=destination)
            self.assertEqual(first, [(destination / name).read_bytes() for name in demo.OUTPUT_FILES])
            with patch.object(dashboard, "DATA_DIR", destination):
                self.assertEqual(dashboard.update_dropdown_options(0), [{"label": "Texas", "value": "Texas"}])
                self.assertEqual(dashboard.update_crisis_map(0).data[0].name, "Flood")
                self.assertEqual(dashboard.update_state_chart(0).data[0].y[0], 1)
                self.assertIn(demo.DEFAULT_TEXT, str(dashboard.update_table("Texas", 0)))
                self.assertIn("Total Reports", str(dashboard.update_stats(0)))
                with dashboard.server.test_client() as client:
                    self.assertEqual(client.get("/").status_code, 200)
                    self.assertEqual(client.get("/_dash-layout").status_code, 200)
        self.assertIs(entry.get_scraped_posts, original_scraper)
        self.assertEqual(entry.MODEL_SERVER_URL, original_url)

    def test_live_csvs_and_scraper_restored_after_exception(self):
        original_scraper = entry.get_scraped_posts
        with TemporaryDirectory() as directory:
            path = Path(directory) / "filtered_posts.csv"
            path.write_bytes(b"existing live output\n")
            with patch.object(entry, "DATA_DIR", Path(directory)):
                with patch.object(entry, "main", side_effect=RuntimeError("interrupted")):
                    with self.assertRaisesRegex(RuntimeError, "interrupted"):
                        demo.process_test_tweet()
            self.assertEqual(path.read_bytes(), b"existing live output\n")
            self.assertFalse((Path(directory) / "crisis_counts.csv").exists())
        self.assertIs(entry.get_scraped_posts, original_scraper)

    def test_missing_model_cannot_pass_using_stale_export(self):
        with TemporaryDirectory() as directory:
            destination = Path(directory)
            for name in demo.OUTPUT_FILES:
                (destination / name).write_text("old data\n")
            with patch.object(entry, "extract_entities", side_effect=requests.ConnectionError("offline")):
                with self.assertRaisesRegex(RuntimeError, "no complete crisis output"):
                    demo.process_test_tweet(output_dir=destination)
            for name in demo.OUTPUT_FILES:
                self.assertEqual((destination / name).read_text(), "old data\n")

    def test_live_mode_calls_model_without_starting_scraper(self):
        response = {"disasters": ["Flood"], "locations": ["Austin Texas"],
                    "city": "Austin", "state": "Texas", "country": "US", "polarity": 0.0}
        with patch.object(entry, "extract_entities", return_value=response) as extract:
            posts, counts = demo.process_test_tweet()
        extract.assert_called_once_with(demo.DEFAULT_TEXT)
        self.assertEqual(len(posts), 1)
        self.assertEqual(counts.iloc[0]["disasters"], "Flood")

    def test_city_csv_parsing_never_executes_code(self):
        with TemporaryDirectory() as directory:
            sentinel = Path(directory) / "executed"
            payload = f"__import__('pathlib').Path({str(sentinel)!r}).touch()"
            counts_file = Path(directory) / "counts.csv"
            pd.DataFrame([{"country": "US", "state": "Texas", "disasters": "Flood",
                           "count": 1, "avg_sentiment": 0, "cities": payload}]).to_csv(counts_file, index=False)
            new_data = pd.DataFrame([{"country": "US", "state": "Texas", "disasters": ["Flood"],
                                      "city": "Austin", "polarity": 0.0}])
            counts = entry.calculate_crisis_counts(new_data, counts_file)
            self.assertFalse(sentinel.exists())
            self.assertEqual(counts.iloc[0]["count"], 2)
            self.assertEqual(counts.iloc[0]["cities"], ["Austin"])
        self.assertEqual(entry.parse_cities('["O\'Fallon"]'), ["O'Fallon"])
        self.assertEqual(entry.parse_cities('{"city": "Austin"}'), [])

    def test_no_crisis_and_scraper_failure_are_empty_results(self):
        with patch.object(entry, "extract_entities", return_value={"disasters": [], "locations": []}):
            filtered = entry.filter_posts(pd.DataFrame(demo.create_mock_post("No crisis")))
        self.assertTrue(entry.calculate_crisis_counts(filtered).empty)
        with patch.object(entry.requests, "get", side_effect=requests.Timeout):
            self.assertEqual(entry.get_scraped_posts(), [])

    def test_fixture_rejects_arbitrary_text(self):
        with self.assertRaisesRegex(ValueError, "only supports"):
            demo.process_test_tweet("Unrelated text", fixture=True)


if __name__ == "__main__":
    unittest.main()
