"""Location regressions using competing gazetteer records, without network or weights."""

import importlib.util
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proj-dev/app/live_demo"))
LIVE_AVAILABLE = all(importlib.util.find_spec(name) for name in ("supabase", "spacy", "pycountry"))


def place(name, state, population=0, aliases="[]", feature="PPL", latitude=1):
    return dict(name=name, stateCode=state, population=population, alternate_list=aliases,
                featureCode=feature, countryCode="US", latitude=latitude, longitude=2)


class GazetteerQuery:
    """Small query substitute retaining real duplicate names and alias data formats."""
    def __init__(self, records):
        self.records = list(records)

    def select(self, _fields):
        return self

    def eq(self, column, value):
        self.records = [row for row in self.records if row.get(column) == value]
        return self

    def ilike(self, column, value):
        pattern = re.escape(value).replace("%", ".*").replace("_", ".")
        self.records = [row for row in self.records if re.fullmatch(pattern, str(row.get(column, "")), re.I)]
        return self

    def order(self, column, desc=False, **_kwargs):
        self.records.sort(key=lambda row: row.get(column, 0), reverse=desc)
        return self

    def limit(self, limit):
        self.records = self.records[:limit]
        return self

    def execute(self):
        return SimpleNamespace(data=self.records)


@unittest.skipUnless(LIVE_AVAILABLE, "requires requirements-live.txt")
class LocationResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, SUPABASE_URL="https://fixture.invalid", SUPABASE_KEY="fixture-only"):
            with patch("supabase.create_client", return_value=Mock()):
                import model_server
        cls.model = model_server

    def setUp(self):
        self.records = [
            place("Perryville", "MO", 8398), place("Perryville", "AK", 113),
            place("Portland", "OR", 600000), place("Portland", "ME", 68000),
            place("Mexico", "MO", 11000), place("Japan", "MO"),
            place("Pacific", "MO", 7000), place("Southwest", "DC"),
            place("Hamilton", "OH", 62000), place("Austin", "TX", 900000),
            place("McAllen", "TX", 140000), place("Lynchburg", "VA", 80000, "['Chibagville']"),
            place("New York City", "NY", 8000000, "['New York', 'NYC']"),
            place("Texas", "TX", feature="ADM1", latitude=3),
            place("Alaska", "AK", feature="ADM1", latitude=4),
            place("New Mexico", "NM", feature="ADM1"), place("West Virginia", "WV", feature="ADM1"),
        ]
        self.client = Mock()
        self.client.table.side_effect = lambda _name: GazetteerQuery(self.records)
        self.patcher = patch.object(self.model, "supabase", self.client)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.model.lookup_city_state_country.cache_clear()
        self.addCleanup(self.model.lookup_city_state_country.cache_clear)

    def resolve(self, text, locations):
        return self.model.standardize_row({"text": text, "locations": locations})

    def test_explicit_state_overrides_largest_city(self):
        result = self.resolve("Earthquake near Perryville, Alaska.", ["Perryville", "Alaska"])
        self.assertEqual((result["city"], result["state"]), ("Perryville", "Alaska"))

    def test_combined_entity_and_abbreviation(self):
        for location in ("Portland, ME", "Portland Maine"):
            with self.subTest(location=location):
                result = self.resolve("Flood in " + location, [location])
                self.assertEqual((result["city"], result["state"]), ("Portland", "Maine"))

    def test_state_hint_is_part_of_cache_key(self):
        for code, name in (("ME", "Maine"), ("OR", "Oregon"), ("ME", "Maine")):
            self.assertEqual(self.resolve(f"Flood in Portland, {code}.", ["Portland"])["state"], name)

    def test_different_cities_get_their_own_state(self):
        result = self.resolve("Flood in Portland, ME and Perryville, AK.", ["Portland", "Perryville"])
        self.assertEqual(result["state"], "Maine")
        self.assertEqual(result["all_locations"][0]["state"], "Alaska")

    def test_same_city_in_two_states_keeps_both(self):
        result = self.resolve("Flood in Portland, ME and Portland, OR.", ["Portland"])
        self.assertEqual({result["state"], result["all_locations"][0]["state"]}, {"Maine", "Oregon"})

    def test_no_fallback_to_other_state_when_qualified_city_is_absent(self):
        result = self.resolve("Flood in Portland, Texas.", ["Portland"])
        self.assertIsNone(result["state"])

    def test_foreign_context_does_not_invent_us_towns(self):
        for text, locations in (
            ("Landslides in Chiba, Japan", ["Chiba", "Japan"]),
            ("Hurricane near Mexico's Pacific coast", ["Mexico", "Pacific", "Southwest"]),
            ("Flood in Hamilton, Ontario, Canada", ["Hamilton", "Ontario", "Canada"]),
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.resolve(text, locations)["state"])
        self.client.table.assert_not_called()

    def test_foreign_names_can_be_explicitly_qualified_us_cities(self):
        result = self.resolve("Flood in Mexico, Missouri.", ["Mexico", "Missouri"])
        self.assertEqual((result["city"], result["state"]), ("Mexico", "Missouri"))

    def test_mixed_international_and_us_post_keeps_explicit_us_place(self):
        result = self.resolve("Flood in Japan and Austin, Texas.", ["Japan", "Austin", "Texas"])
        self.assertEqual((result["city"], result["state"]), ("Austin", "Texas"))

    def test_state_names_are_whole_names(self):
        self.assertEqual(self.resolve("Flood in New Mexico", ["New Mexico"])["state"], "New Mexico")
        self.assertEqual(self.resolve("Flood in West Virginia", ["West Virginia"])["state"], "West Virginia")
        self.assertIsNone(self.resolve("Flood near Virginia Beach Road", ["Virginia Beach Road"])["state"])

    def test_case_and_hashtag_duplicates_do_not_add_records(self):
        result = self.resolve("Flood in Austin Texas #austin #texas", ["Austin", "Texas", "austin", "texas", "TX"])
        self.assertEqual(result["city"], "Austin")
        self.assertEqual(len(result["all_locations"]), 1)
        self.assertEqual(result["all_locations"][0]["state"], "Texas")

    def test_mixed_case_exact_name_and_whole_alias(self):
        self.assertEqual(self.resolve("Flood in McAllen, TX", ["McAllen"])["city"], "McAllen")
        self.assertEqual(self.resolve("Flood in NYC", ["NYC"])["city"], "New York City")
        self.assertIsNone(self.resolve("Flood in Chiba", ["Chiba"])["state"])

    def test_alias_data_is_not_executed(self):
        self.assertEqual(self.model.exact_aliases("__import__('os').system('false')"), set())
        self.assertEqual(self.model.exact_aliases(",NYC,New York,"), {"", "nyc", "new york"})

    def test_wildcards_cannot_select_arbitrary_city(self):
        self.assertIsNone(self.resolve("Flood in %", ["%"])["state"])
        self.client.table.assert_not_called()

    def test_lowercase_words_are_not_state_abbreviations(self):
        from location_context import adjacent_states, state_code
        self.assertEqual(adjacent_states("Portland", "Flood in Portland or nearby"), set())
        self.assertIsNone(state_code("in"))
        self.assertIsNone(state_code("me"))


if __name__ == "__main__":
    unittest.main()
