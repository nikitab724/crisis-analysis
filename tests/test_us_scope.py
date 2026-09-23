"""Foreign and unresolved records must stay out of all US dashboard surfaces."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proj-dev/app/live_demo"))
import dash_client as dashboard  # noqa: E402
import entry  # noqa: E402
from pipeline_status import read_status  # noqa: E402
from us_scope import is_us_location, us_records  # noqa: E402


def location(**changes):
    return {"country": "US", "state": "Texas", "city": "Austin", "location_status": "matched",
            "latitude": 30.2672, "longitude": -97.7431, **changes}


def result(**changes):
    return {**location(), "disasters": ["Flood"], "locations": ["Austin", "Texas"],
            "all_locations": [], "polarity": 0, **changes}


class USScopeTests(unittest.TestCase):
    def test_requires_explicit_us_country_supported_state_and_successful_match(self):
        for country in (None, "", float("nan"), "CA", "JP", "GE"):
            self.assertFalse(is_us_location(location(country=country)))
        for state in (None, "", "Ontario", "Unknown", "Puerto Rico"):
            self.assertFalse(is_us_location(location(state=state)))
        for status in ("unresolved", "ambiguous", "error", "unexpected"):
            self.assertFalse(is_us_location(location(location_status=status)))
        for state in ("Texas", "TX", "Alaska", "Hawaii", "District of Columbia", "DC"):
            self.assertTrue(is_us_location(location(state=state)))
        self.assertTrue(is_us_location({"country": "US", "state": "Texas"}))
        self.assertTrue(us_records(pd.DataFrame()).empty)

    def test_mixed_post_keeps_only_us_locations_even_when_first_location_is_foreign(self):
        response = result(country="CA", state="Ontario", city="Hamilton",
                          all_locations=[location(), location(country="JP", state=None, city="Tokyo"),
                                         location(country=None)])
        with patch.object(entry, "extract_entities", return_value=response):
            filtered = entry.filter_posts(pd.DataFrame([{"text": "Flood in Hamilton, Canada and Austin, Texas."}]))
        self.assertEqual(len(filtered), 1)
        self.assertEqual((filtered.iloc[0]["country"], filtered.iloc[0]["city"]), ("US", "Austin"))

    def test_missing_country_is_never_defaulted_to_us(self):
        response = result()
        response.pop("country")
        with patch.object(entry, "extract_entities", return_value=response):
            self.assertTrue(entry.filter_posts(pd.DataFrame([{"text": "Flood in Austin."}])).empty)

    def test_foreign_batch_is_analyzed_without_saving_or_counting_it(self):
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.object(entry, "get_scraped_posts", return_value=[{"text": "Flood in Canada"}]):
                with patch.object(entry, "extract_entities", return_value=result(country="CA", state="Ontario")):
                    entry.main(output_dir=directory)
            status = read_status(directory)
            self.assertEqual(status["posts_processed"], 1)
            self.assertEqual(status["matched_records"], 0)
            self.assertEqual(status["model_errors"], 0)
            self.assertFalse((Path(directory) / "filtered_posts.csv").exists())

    def test_old_foreign_csv_rows_are_hidden_from_all_dashboard_views(self):
        common = {"disasters": "['Flood']", "created_at": "2026-09-22T12:00:00Z", "sentiment": "Neutral"}
        with TemporaryDirectory() as directory:
            path = Path(directory)
            pd.DataFrame([
                {**common, **location(), "text": "US event"},
                {**common, **location(country="CA", state="Ontario"), "text": "Foreign event"},
                {**common, **location(country=None, state=None), "text": "Unresolved event"},
                {**common, **location(country="CA"), "text": "Conflicting country"},
            ]).to_csv(path / "filtered_posts.csv", index=False)
            pd.DataFrame([
                {"country": country, "state": state, "disasters": "Flood", "count": count,
                 "avg_sentiment": 0, "cities": "[]", "severity": 0}
                for country, state, count in (("US", "Texas", 1), ("CA", "Ontario", 8), (None, "Hawaii", 10))
            ]).to_csv(path / "crisis_counts.csv", index=False)
            with patch.object(dashboard, "DATA_DIR", path):
                table = str(dashboard.update_table(None, 0))
                self.assertIn("US event", table)
                for text in ("Foreign event", "Unresolved event", "Conflicting country"):
                    self.assertNotIn(text, table)
                self.assertEqual(dashboard.update_dropdown_options(0), [{"label": "Texas", "value": "Texas"}])
                self.assertEqual(list(dashboard.load_dashboard_counts()["state"]), ["Texas"])
                self.assertEqual(dashboard.load_dashboard_counts()["count"].sum(), 1)
                self.assertEqual(list(dashboard.update_crisis_map(0).data[0].text), ["Austin, Texas"])
            new_posts = pd.DataFrame([result(), result(country="CA", state="Ontario")])
            counts = entry.calculate_crisis_counts(new_posts, path / "crisis_counts.csv")
            self.assertEqual(list(counts["country"]), ["US"])
            self.assertEqual(list(counts["count"]), [2])
            old_counts = entry.calculate_crisis_counts(pd.DataFrame(), path / "crisis_counts.csv")
            self.assertEqual(list(old_counts["country"]), ["US"])


if __name__ == "__main__":
    unittest.main()
