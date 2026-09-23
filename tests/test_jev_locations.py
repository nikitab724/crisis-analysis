"""Location-choice contract tests; provider accuracy is tested separately."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "proj-dev/app/live_demo"))
import entry  # noqa: E402
from jev_relevance import JevRelevance, RelevanceUnavailable  # noqa: E402


def groups():
    return [{"mention": "Portland", "candidates": [
        {"geonameid": 5746545, "city": "Portland", "state": "Oregon", "country": "US",
         "latitude": 45.52345, "longitude": -122.67621},
        {"geonameid": 4975802, "city": "Portland", "state": "Maine", "country": "US",
         "latitude": 43.66147, "longitude": -70.25533},
    ]}]


def choice_response(choice="place_1", probability=0.97, context=0.98):
    probabilities = {"place_0": (1-probability)/2, "place_1": (1-probability)/2,
                     "unknown": (1-probability)/2}
    probabilities[choice] = probability
    return {"answers": {
        "location_0": {"type": "choice", "choice": choice, "probabilities": probabilities},
        "context_0": {"type": "boolean", "probability": context},
    }}


class JevLocationTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.session.post.return_value = Mock(status_code=200)
        self.client = JevRelevance("fixture-key", session=self.session)

    def answer(self, response):
        self.session.post.return_value.json.return_value = response

    def test_choice_uses_database_coordinates_and_parallel_evidence_question(self):
        self.answer(choice_response())
        result = self.client.choose_locations("Flood in Portland near Casco Bay", groups())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['state'], 'Maine')
        self.assertEqual(result[0]['longitude'], -70.25533)
        self.assertEqual(result[0]['geonameid'], 4975802)
        self.assertEqual(result[0]['location_status'], 'matched')
        self.assertEqual(result[0]['location_probability'], 0.97)
        payload = self.session.post.call_args.kwargs['json']
        self.assertEqual(set(payload['questions']), {'location_0', 'context_0'})
        self.assertEqual(set(payload['questions']['location_0']['criteria']), {'place_0', 'place_1', 'unknown'})
        self.assertNotIn('longitude', str(payload))

    def test_unknown_low_choice_and_missing_context_all_abstain(self):
        for choice, score, context in [('unknown', .99, .99), ('place_0', .89, .99), ('place_0', .99, .2)]:
            with self.subTest(choice=choice, score=score, context=context):
                self.answer(choice_response(choice, score, context))
                client = JevRelevance('fixture-key', session=self.session)
                self.assertEqual(client.choose_locations('Flood in Portland', groups()), [])

    def test_same_name_and_state_remain_ambiguous_even_with_high_score(self):
        candidates = groups()
        candidates[0]['candidates'][0]['state'] = 'Maine'
        self.answer(choice_response())
        self.assertEqual(self.client.choose_locations('Flood in Portland Maine', candidates), [])

    def test_malformed_choice_answers_fail_closed(self):
        malformed = []
        for field, value in [('choice', 'invented'), ('probabilities', {'place_1': 1}),
                             ('probabilities', {'place_0': .9, 'place_1': .9, 'unknown': .9}),
                             ('probabilities', {'place_0': float('nan'), 'place_1': .9, 'unknown': .1}),
                             ('probabilities', {'place_0': .95, 'place_1': .04, 'unknown': .01}),
                             ('type', 'boolean')]:
            answer = choice_response()
            answer['answers']['location_0'][field] = value
            malformed.append(answer)
        malformed.extend([{'answers': {}}, {'answers': {'location_0': None}}, {'answers': []}])
        for answer in malformed:
            with self.subTest(answer=answer):
                self.answer(answer)
                with self.assertRaises(RelevanceUnavailable):
                    JevRelevance('fixture-key', session=self.session).choose_locations('post', groups())

    def test_invalid_or_large_candidate_lists_never_reach_provider(self):
        for change in ({'country': 'CA'}, {'latitude': float('nan')}, {'longitude': 190}, {'geonameid': None}):
            candidate_groups = groups()
            candidate_groups[0]['candidates'][0].update(change)
            with self.assertRaises(RelevanceUnavailable):
                self.client.choose_locations('post', candidate_groups)
        with self.assertRaises(RelevanceUnavailable):
            self.client.choose_locations('post', groups()*9)
        self.assertEqual(self.client.choose_locations('post', []), [])
        self.session.post.assert_not_called()

    def test_stages_share_budget_and_cache_includes_questions_and_candidate_identity(self):
        self.client.max_calls = 2
        self.answer(choice_response())
        self.client.choose_locations('post', groups())
        self.client.choose_locations('post', groups())
        self.answer({'answers': {'candidate_0': {'type': 'boolean', 'probability': .95}}})
        self.client.screen('post', '', [{'city': 'Portland', 'state': 'Maine', 'disasters': ['Flood']}])
        changed = groups()
        changed[0]['candidates'][1]['geonameid'] = 123
        with self.assertRaisesRegex(RelevanceUnavailable, 'cap reached'):
            self.client.choose_locations('post', changed)
        self.assertEqual(self.session.post.call_count, 2)

    def test_processor_selects_then_screens_and_removes_supporting_state(self):
        model_result = {'disasters': ['Flood'], 'locations': ['Portland', 'Maine'],
                        'city': None, 'state': 'Maine', 'country': 'US',
                        'location_status': 'matched', 'location_choices': groups(),
                        'unresolved_locations': ['Portland'], 'location_review': 'Unresolved mentions: Portland'}
        choice = Mock(status_code=200)
        choice.json.return_value = choice_response()
        screen = Mock(status_code=200)
        screen.json.return_value = {'answers': {'candidate_0': {'type': 'boolean', 'probability': .96}}}
        self.session.post.side_effect = [choice, screen]
        stats = {}
        with patch.object(entry, 'extract_entities', return_value=model_result), \
                patch.object(entry, 'get_relevance_client', return_value=self.client):
            result = entry.filter_posts(pd.DataFrame([{'text': 'Flood in Portland near Casco Bay'}]), relevance_stats=stats)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]['city'], 'Portland')
        self.assertEqual(result.iloc[0]['location_review'], '')
        self.assertEqual(result.iloc[0]['relevance_status'], 'passed')
        self.assertEqual(result.iloc[0]['location_model'], 'typesafe-ai/jev')
        self.assertEqual(stats['location_resolved'], 1)
        self.assertEqual(stats['relevance_checked'], 1)

    def test_choice_failure_is_observable_and_does_not_become_nlp_error(self):
        model_result = {'disasters': ['Flood'], 'locations': ['Portland'], 'location_choices': groups()}
        self.session.post.return_value.status_code = 500
        stats, progress = {}, Mock()
        with patch.object(entry, 'extract_entities', return_value=model_result), \
                patch.object(entry, 'get_relevance_client', return_value=self.client), redirect_stdout(io.StringIO()):
            result = entry.filter_posts(pd.DataFrame([{'text': 'Flood in Portland'}]), progress, stats)
        self.assertTrue(result.empty)
        self.assertEqual(stats, {'location_errors': 1})
        progress.assert_called_once_with(1, 0)

    def test_unique_location_needs_only_relevance_call(self):
        model_result = {'disasters': ['Flood'], 'locations': ['Austin', 'Texas'],
                        'city': 'Austin', 'state': 'Texas', 'country': 'US', 'location_choices': []}
        self.answer({'answers': {'candidate_0': {'type': 'boolean', 'probability': .95}}})
        with patch.object(entry, 'extract_entities', return_value=model_result), \
                patch.object(entry, 'get_relevance_client', return_value=self.client):
            result = entry.filter_posts(pd.DataFrame([{'text': 'Flood in Austin Texas'}]))
        self.assertEqual(len(result), 1)
        self.assertEqual(self.session.post.call_count, 1)

    def test_abstention_keeps_other_resolved_locations_for_screening(self):
        model_result = {'disasters': ['Flood'], 'locations': ['Austin', 'Portland'],
                        'city': 'Austin', 'state': 'Texas', 'country': 'US',
                        'location_choices': groups(), 'unresolved_locations': ['Portland']}
        reviewer = Mock()
        reviewer.choose_locations.return_value = []
        reviewer.screen.side_effect = lambda _text, _date, records: records
        with patch.object(entry, 'extract_entities', return_value=model_result), \
                patch.object(entry, 'get_relevance_client', return_value=reviewer):
            result = entry.filter_posts(pd.DataFrame([{'text': 'Flood in Austin and Portland'}]))
        self.assertEqual(list(result['city']), ['Austin'])
        self.assertIn('Portland', result.iloc[0]['location_review'])


if __name__ == '__main__':
    unittest.main()
