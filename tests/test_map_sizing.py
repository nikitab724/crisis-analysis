"""Map circles measure saved records, not distance, sentiment, or affected area."""

import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proj-dev/app/live_demo"))
import dash_client as dashboard  # noqa: E402


def post(city="Austin", state="Texas", lat=30.2672, lon=-97.7431, disaster="Flood", **extra):
    return dict(city=city, state=state, latitude=lat, longitude=lon,
                disasters=str([disaster]), country="US", **extra)


class MapSizingTests(unittest.TestCase):
    def figure(self, records):
        with TemporaryDirectory() as directory:
            pd.DataFrame(records).to_csv(Path(directory) / "filtered_posts.csv", index=False)
            # An unrelated or stale state aggregate must not drive point sizes.
            pd.DataFrame([{"count": 99999, "severity": 999}]).to_csv(Path(directory) / "crisis_counts.csv", index=False)
            with patch.object(dashboard, "DATA_DIR", Path(directory)):
                return dashboard.update_crisis_map(0)

    def test_circle_area_is_proportional_to_count(self):
        self.assertEqual([dashboard.marker_diameter(n) for n in (1, 4, 16, 64)], [8, 16, 32, 64])
        self.assertEqual((dashboard.marker_diameter(4) / dashboard.marker_diameter(1)) ** 2, 4)

    def test_city_counts_use_their_own_coordinates_not_a_centroid(self):
        rows = [post()] + [post("Dallas", lat=32.7767, lon=-96.797)] * 4
        fig = self.figure(rows)
        trace = fig.data[0]
        self.assertEqual(trace.name, "Flood")
        values = {name: (lat, lon, size, info[0]) for name, lat, lon, size, info in
                  zip(trace.text, trace.lat, trace.lon, trace.marker.size, trace.customdata)}
        self.assertEqual(values["Austin, Texas"], (30.2672, -97.7431, 8, 1))
        self.assertEqual(values["Dallas, Texas"], (32.7767, -96.797, 16, 4))
        self.assertEqual(trace.marker.sizemode, "diameter")
        self.assertEqual(trace.marker.sizeref, 1)

    def test_other_locations_and_outliers_do_not_rescale_existing_circle(self):
        before = self.figure([post()] * 4)
        after = self.figure([post()] * 4 + [post("Honolulu", "Hawaii", 21.3, -157.8)] * 100)
        old_size = before.data[0].marker.size[0]
        new_sizes = dict(zip(after.data[0].text, after.data[0].marker.size))
        self.assertEqual(new_sizes["Austin, Texas"], old_size)
        self.assertEqual(new_sizes["Honolulu, Hawaii"], 64)
        big = list(after.data[0].text).index("Honolulu, Hawaii")
        self.assertEqual(after.data[0].customdata[big][0], 100)
        self.assertIn("capped", after.data[0].customdata[big][2])

    def test_state_only_point_is_labeled_and_uses_same_count_scale(self):
        fig = self.figure([post(), post(city=None, lat=None, lon=None)])
        self.assertEqual(list(fig.data[0].marker.size), [8, 8])
        points = dashboard.map_points_from_posts(pd.DataFrame([post(city=None, lat=None, lon=None)]))
        self.assertEqual(points[0]["precision"], "State centroid (approximate)")
        self.assertEqual((points[0]["lat"], points[0]["lon"]), dashboard.state_coordinates["Texas"])

    def test_missing_or_invalid_city_coordinates_use_explicit_state_fallback(self):
        for lat, lon in ((None, None), (float("nan"), 3), (float("inf"), 4), (91, 0), (25, 181), ("bad", 2)):
            with self.subTest(lat=lat, lon=lon):
                points = dashboard.map_points_from_posts(pd.DataFrame([post(lat=lat, lon=lon)]))
                self.assertEqual(points[0]["location"], "Texas")
                self.assertIn("approximate", points[0]["precision"])
                self.assertTrue(math.isfinite(points[0]["lat"]))

    def test_unresolved_foreign_and_unknown_states_are_excluded(self):
        rows = [post(state=None), post(state="Not a state"), post(location_status="ambiguous"),
                {**post(), "country": "CA"}]
        self.assertEqual(dashboard.map_points_from_posts(pd.DataFrame(rows)), [])
        fig = self.figure(rows)
        self.assertEqual(len(fig.data), 0)
        self.assertIn("No reports yet", fig.layout.annotations[0].text)

    def test_same_count_means_same_size_across_disaster_types(self):
        fig = self.figure([post(disaster="Flood", polarity=-1)] * 4 +
                          [post(disaster="Wildfire", polarity=1)] * 4)
        self.assertEqual([trace.marker.size[0] for trace in fig.data], [16, 16])
        self.assertEqual([trace.customdata[0][0] for trace in fig.data], [4, 4])

    def test_first_disaster_and_saved_record_counts_match_existing_aggregation(self):
        rows = [{**post(), "disasters": "['Flood', 'Wildfire']"}, post(state="TX")]
        points = dashboard.map_points_from_posts(pd.DataFrame(rows))
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["disaster"], "Flood")
        self.assertEqual(points[0]["count"], 2)

    def test_invalid_size_inputs_are_finite_and_safe(self):
        for value in (None, "bad", float("nan"), float("inf"), -1, 0):
            with self.subTest(value=value):
                self.assertEqual(dashboard.marker_diameter(value), 0)


if __name__ == "__main__":
    unittest.main()
