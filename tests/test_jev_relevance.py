"""Contract/failure tests; these do not establish the real model's accuracy."""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proj-dev/app/live_demo"))
import dash_client as dashboard  # noqa: E402
import entry  # noqa: E402
from jev_relevance import ENDPOINT, JevRelevance, RelevanceUnavailable, get_relevance_client  # noqa: E402
from pipeline_status import read_status  # noqa: E402
import process_test_tweet as demo  # noqa: E402


def record(**extra):
    return {"country": "US", "state": "Texas", "city": "Austin", "disasters": ["Pandemic"], **extra}


def response(*values):
    value = Mock(status_code=200)
    value.json.return_value = {"answers": {
        f"candidate_{i}": {"type": "boolean", "probability": probability}
        for i, probability in enumerate(values)
    }}
    return value


class JevRelevanceTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.client = JevRelevance("fixture-secret", session=self.session)

    def test_gateway_contract_one_call_for_multiple_locations_and_disasters(self):
        self.session.post.return_value = response(0.05, 0.95, 0.2)
        records = [record(disasters=["Pandemic", "Flood"]), record(city="Dallas")]
        kept = self.client.screen("Flood plus a metaphor about a pandemic", "2026-09-22", records)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["disasters"], ["Flood"])
        self.assertEqual(kept[0]["relevance_status"], "passed")
        self.assertEqual(kept[0]["relevance_probability"], 0.95)
        args, kwargs = self.session.post.call_args
        self.assertEqual(args, (ENDPOINT,))
        self.assertEqual(kwargs["json"]["model"], "typesafe-ai/jev")
        self.assertEqual(len(kwargs["json"]["questions"]), 3)
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer fixture-secret"})
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (3, 6))
        self.assertNotIn("fixture-secret", str(kwargs["json"]))

    def test_uncertain_or_irrelevant_decisions_are_not_published(self):
        self.session.post.return_value = response(0.79)
        self.assertEqual(self.client.screen("Unclear pandemic mention", "", [record()]), [])

    def test_same_post_is_cached_but_different_location_is_checked_again(self):
        self.session.post.return_value = response(0.9)
        self.client.screen("post", "", [record()])
        self.client.screen("post", "", [record()])
        self.client.screen("post", "", [record(city="Dallas")])
        self.assertEqual(self.session.post.call_count, 2)

    def test_request_budget_is_enforced_and_never_falls_back_to_approval(self):
        self.client.max_calls = 1
        self.session.post.return_value = response(0.9)
        self.client.screen("first", "", [record()])
        with self.assertRaisesRegex(RelevanceUnavailable, "cap reached"):
            self.client.screen("second", "", [record()])
        self.assertEqual(self.session.post.call_count, 1)

    def test_timeout_has_no_retry_storm_or_secret_in_error(self):
        self.session.post.side_effect = requests.Timeout("fixture-secret")
        for _ in range(2):
            with self.assertRaises(RelevanceUnavailable) as raised:
                self.client.screen("post", "", [record()])
            self.assertNotIn("fixture-secret", str(raised.exception))
        self.assertEqual(self.session.post.call_count, 1)

    def test_zero_cap_continues_past_default_limit_and_still_caches(self):
        client = JevRelevance("fixture-secret", max_calls=0, session=self.session)
        client.calls = 200
        self.session.post.return_value = response(0.9)
        for text in ("first", "second", "first"):
            self.assertEqual(len(client.screen(text, "", [record()])), 1)
        self.assertEqual(client.calls, 202)
        self.assertEqual(self.session.post.call_count, 2)
        self.assertEqual(client.diagnostics()['jev_max_calls'], 0)

    def test_zero_cap_environment_and_invalid_caps(self):
        get_relevance_client.cache_clear()
        self.addCleanup(get_relevance_client.cache_clear)
        with patch.dict(os.environ, CRISIS_RELEVANCE_MODE='jev', AI_GATEWAY_API_KEY='fixture-secret',
                        JEV_MAX_CALLS_PER_RUN='0'):
            self.assertEqual(get_relevance_client().max_calls, 0)
        for limit in (-1, True, 0.5, float('nan')):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                JevRelevance('fixture-secret', max_calls=limit)

    def test_malformed_missing_and_nonfinite_probabilities_are_rejected(self):
        for probability in (None, "0.9", True, float("nan"), float("inf"), -0.1, 1.1):
            with self.subTest(probability=probability):
                self.session.post.return_value = response(probability)
                client = JevRelevance("fixture-secret", session=self.session)
                with self.assertRaises(RelevanceUnavailable):
                    client.screen("post", "", [record()])
        self.session.post.return_value = response()
        with self.assertRaises(RelevanceUnavailable):
            JevRelevance("fixture-secret", session=self.session).screen("post", "", [record()])

    def test_http_failure_skips_review_instead_of_leaking_provider_response(self):
        self.session.post.return_value = Mock(status_code=429)
        with self.assertRaises(RelevanceUnavailable):
            self.client.screen("post", "", [record()])

    def test_disabled_mode_is_offline_and_enabled_mode_requires_key(self):
        get_relevance_client.cache_clear()
        self.addCleanup(get_relevance_client.cache_clear)
        with patch.dict(os.environ, {"CRISIS_RELEVANCE_MODE": "off"}):
            self.assertIsNone(get_relevance_client())
        get_relevance_client.cache_clear()
        with patch.dict(os.environ, {"CRISIS_RELEVANCE_MODE": "jev", "AI_GATEWAY_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "AI_GATEWAY_API_KEY"):
                get_relevance_client()

    def test_non_us_and_non_crisis_posts_never_reach_jev(self):
        reviewer = Mock()
        response_data = {**record(country="CA", state="Ontario"), "locations": ["Canada"]}
        with patch.object(entry, "get_relevance_client", return_value=reviewer):
            with patch.object(entry, "extract_entities", return_value=response_data):
                self.assertTrue(entry.filter_posts(pd.DataFrame([{"text": "Pandemic in Canada"}])).empty)
            with patch.object(entry, "extract_entities", return_value={"disasters": [], "locations": []}):
                self.assertTrue(entry.filter_posts(pd.DataFrame([{"text": "Hello"}])).empty)
        reviewer.screen.assert_not_called()

    def test_fixture_is_offline_even_if_jev_is_configured(self):
        reviewer = Mock()
        with patch.object(entry, "get_relevance_client", return_value=reviewer):
            with redirect_stdout(io.StringIO()):
                posts, _counts = demo.process_test_tweet(fixture=True)
        self.assertEqual(len(posts), 1)
        reviewer.screen.assert_not_called()

    def test_screening_failure_is_visible_and_is_not_a_model_error_or_saved_post(self):
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.dict(os.environ, {"CRISIS_RELEVANCE_MODE": "jev"}):
                with patch.object(entry, "get_relevance_client", return_value=self.client):
                    with patch.object(entry, "get_scraped_posts", return_value=[{"text": "Pandemic in Texas"}]):
                        with patch.object(entry, "extract_entities", return_value={**record(), "locations": ["Texas"]}):
                            self.session.post.side_effect = requests.Timeout()
                            entry.main(output_dir=directory)
            status = read_status(directory)
            self.assertEqual(status["relevance_errors"], 1)
            self.assertEqual(status["model_errors"], 0)
            self.assertEqual(status["posts_processed"], 1)
            self.assertEqual(status["matched_records"], 0)
            self.assertFalse((Path(directory) / "filtered_posts.csv").exists())
            with patch.object(dashboard, "DATA_DIR", Path(directory)), patch.object(dashboard, "PIPELINE_MODE", "live"):
                self.assertIsNone(dashboard.update_activity(0))


if __name__ == "__main__":
    unittest.main()
