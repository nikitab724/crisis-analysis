"""Semantic classification contracts; mocked probabilities do not measure accuracy."""
from contextlib import redirect_stdout
import importlib.util
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
sys.path.insert(0, str(ROOT / 'proj-dev/app/live_demo'))
import entry  # noqa: E402
import process_test_tweet as demo  # noqa: E402
from crisis_classification import DISASTER_DEFINITIONS, classification_mode  # noqa: E402
from jev_relevance import JevRelevance, RelevanceUnavailable  # noqa: E402
from pipeline_status import read_status  # noqa: E402

ENV = {'CRISIS_CLASSIFICATION_MODE': 'jev', 'CRISIS_RELEVANCE_MODE': 'jev'}
TEXT = 'The streets in Austin Texas are underwater and residents are evacuating now.'


def place(**extra):
    return {'city': 'Austin', 'state': 'Texas', 'country': 'US', 'latitude': 30.2672,
            'longitude': -97.7431, 'disasters': [], **extra}


def decisions(*scores):
    return Mock(status_code=200, json=lambda: {'answers': {
        f'location_{i}_type_{j}': {'type': 'boolean', 'probability': values.get(label, .01)}
        for i, values in enumerate(scores) for j, label in enumerate(DISASTER_DEFINITIONS)
    }})


class JevClassificationTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.client = JevRelevance('fixture-secret', session=self.session)

    def test_assigns_labels_without_rule_candidates_in_one_call(self):
        self.session.post.return_value = decisions({'Flood': .97})
        result = self.client.classify(TEXT, '2026-09-23', [place()])
        self.assertEqual(result[0]['disasters'], ['Flood'])
        self.assertEqual(result[0]['classification_mode'], 'jev')
        self.assertEqual(result[0]['relevance_probability'], .97)
        self.session.post.assert_called_once()
        payload = self.session.post.call_args.kwargs['json']
        self.assertNotIn('disasters', payload['state']['locations'][0])
        self.assertEqual(len(payload['questions']), len(DISASTER_DEFINITIONS))
        self.assertNotIn('fixture-secret', str(payload))

    def test_houston_text_classification_does_not_assume_texas(self):
        text = 'The streets in Houston are underwater and people are trapped in their homes.'
        self.session.post.return_value = Mock(status_code=200, json=lambda: {'answers': {
            f'type_{i}': {'type': 'boolean', 'probability': .93 if label == 'Flood' else .01}
            for i, label in enumerate(DISASTER_DEFINITIONS)}})
        result = self.client.classify_text(text)
        self.assertEqual(result['disasters'], ['Flood'])
        state = self.session.post.call_args.kwargs['json']['state']
        self.assertEqual(state['post_text'], text)
        self.assertNotIn('locations', state)
        self.assertNotIn('Texas', str(state))

    def test_batch_screen_only_excludes_confident_negatives(self):
        self.session.post.return_value = Mock(status_code=200, json=lambda: {'answers': {
            f'post_{i}': {'type': 'boolean', 'probability': score}
            for i, score in enumerate([.01, .2, .5, .99])}})
        self.assertEqual(self.client.event_candidates(['joke', 'uncertain', 'reply', TEXT]),
                         [False, True, True, True])
        self.session.post.assert_called_once()
        with self.assertRaises(RelevanceUnavailable):
            self.client.event_candidates(['x'] * 17)

    def test_batch_screen_saves_nlp_work_but_retains_uncertain_posts(self):
        rows = pd.DataFrame([{'text': 'A flood of compliments.'}, {'text': TEXT}])
        with patch.dict(os.environ, {**ENV, 'JEV_BATCH_SCREEN': 'on'}), \
                patch.object(entry, 'get_relevance_client', return_value=self.client), \
                patch.object(self.client, 'event_candidates', return_value=[False, True]) as screen, \
                patch.object(entry, 'extract_entities', return_value={**place(), 'locations': ['Austin']}) as model:
            self.session.post.return_value = decisions({'Flood': .96})
            result = entry.filter_posts(rows, prefilter=True)
        screen.assert_called_once_with(list(rows.text))
        model.assert_called_once_with(TEXT, rule_gate=False)
        self.assertEqual(list(result.text), [TEXT])

    def test_batch_screen_reuses_individual_decisions_when_retry_batch_changes(self):
        self.session.post.return_value = Mock(status_code=200, json=lambda: {'answers': {
            'post_0': {'type': 'boolean', 'probability': .01},
            'post_1': {'type': 'boolean', 'probability': .8}}})
        self.assertEqual(self.client.event_candidates(['joke', TEXT]), [False, True])
        self.assertEqual(self.client.event_candidates([TEXT, 'joke', TEXT]), [True, False, True])
        self.assertEqual(self.session.post.call_count, 1)
        self.session.post.return_value = Mock(status_code=200, json=lambda: {'answers': {
            'post_0': {'type': 'boolean', 'probability': .5}}})
        self.assertEqual(self.client.event_candidates([TEXT, 'new post', 'joke']), [True, True, False])
        self.assertEqual(self.session.post.call_args.kwargs['json']['state']['posts'], ['new post'])

    def test_failed_screen_does_not_cache_a_negative_and_cache_is_bounded(self):
        self.session.post.side_effect = requests.Timeout()
        with self.assertRaises(RelevanceUnavailable):
            self.client.event_candidates([TEXT])
        self.assertEqual(len(self.client._event_cache), 0)
        self.client.retry_after = 0
        self.session.post.side_effect = None
        self.session.post.return_value = Mock(status_code=200, json=lambda: {'answers': {
            'post_0': {'type': 'boolean', 'probability': .8}}})
        self.client._event_cache.update((f'old-{i}', False) for i in range(2048))
        self.assertEqual(self.client.event_candidates([TEXT]), [True])
        self.assertEqual(len(self.client._event_cache), 2048)
        self.assertNotIn('old-0', self.client._event_cache)

    def test_batch_screen_chunks_requests_and_failure_keeps_receipt(self):
        rows = pd.DataFrame([{'text': f'Flood of compliments {i}'} for i in range(33)])
        with patch.dict(os.environ, {**ENV, 'JEV_BATCH_SCREEN': 'on'}), \
                patch.object(entry, 'get_relevance_client', return_value=self.client), \
                patch.object(self.client, 'event_candidates', side_effect=lambda texts: [False] * len(texts)) as screen, \
                patch.object(entry, 'extract_entities') as model:
            self.assertTrue(entry.filter_posts(rows, prefilter=True).empty)
        self.assertEqual([len(call.args[0]) for call in screen.call_args_list], [16, 16, 1])
        model.assert_not_called()
        batch = entry.CollectedPosts([{'text': TEXT, 'created_at': pd.Timestamp.now(tz='UTC').isoformat()}], receipt='c'*32)
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), \
                patch.dict(os.environ, {**ENV, 'JEV_BATCH_SCREEN': 'on', 'CRISIS_PIPELINE_MODE': 'live'}), \
                patch.object(entry, 'get_scraped_posts', return_value=batch), \
                patch.object(entry, 'get_relevance_client', return_value=self.client), \
                patch.object(self.client, 'event_candidates', side_effect=RelevanceUnavailable('Retry later')), \
                patch.object(entry, 'acknowledge_posts') as ack:
            entry.main(output_dir=directory)
            self.assertEqual(read_status(directory)['phase'], 'error')
            self.assertFalse((Path(directory)/'filtered_posts.csv').exists())
        ack.assert_not_called()

    def test_replaces_wrong_rule_label_and_keeps_tornado_separate(self):
        self.session.post.return_value = decisions({'Tornado': .95})
        kept = self.client.classify('A tornado touched down in Austin.', '', [place(disasters=['Hurricane'])])
        self.assertEqual(kept[0]['disasters'], ['Tornado'])
        self.assertEqual(kept[0]['latitude'], 30.2672)

    def test_multiple_labels_are_bound_to_each_location(self):
        self.session.post.return_value = decisions({'Flood': .95, 'Hurricane': .91}, {'Wildfire': .99})
        result = self.client.classify('Two events in different places.', '', [place(), place(city='Dallas')])
        self.assertEqual(result[0]['disasters'], ['Hurricane', 'Flood'])
        self.assertEqual(result[1]['disasters'], ['Wildfire'])
        self.assertEqual(result[1]['city'], 'Dallas')
        self.assertEqual(self.session.post.call_count, 1)

    def test_no_confident_supported_label_means_no_publication(self):
        self.session.post.return_value = decisions({'Flood': .79})
        self.assertEqual(self.client.classify('Could mean anything.', '', [place()]), [])

    def test_batches_large_location_sets_without_unbounded_questions(self):
        self.session.post.side_effect = [decisions({'Flood': .95}, {'Flood': .96}), decisions({'Flood': .98})]
        places = [place(city=city) for city in ['Austin', 'Dallas', 'Houston']]
        self.assertEqual(len(self.client.classify(TEXT, '', places)), 3)
        self.assertEqual(self.session.post.call_count, 2)
        self.assertTrue(all(len(call.kwargs['json']['questions']) <= 32 for call in self.session.post.call_args_list))

    def test_later_chunk_failure_does_not_publish_partial_decisions(self):
        self.session.post.side_effect = [decisions({'Flood': .95}, {'Flood': .95}), requests.Timeout()]
        with self.assertRaises(RelevanceUnavailable):
            self.client.classify(TEXT, '', [place(city=name) for name in ['Austin', 'Dallas', 'Houston']])

    def test_same_post_reuses_cache_and_existing_cap_is_shared(self):
        self.client.max_calls = 1
        self.session.post.return_value = decisions({'Flood': .95})
        self.client.classify(TEXT, '', [place()])
        self.client.classify(TEXT, '', [place()])
        with self.assertRaisesRegex(RelevanceUnavailable, 'cap reached'):
            self.client.screen('another post', '', [place(disasters=['Flood'])])
        self.session.post.assert_called_once()

    def test_bounds_country_and_response_validation(self):
        for text, places in [('x' * 10001, [place()]), (TEXT, [place()] * 9),
                             (TEXT, [place(country='CA', state='Ontario')])]:
            with self.subTest(text=text[:20], places=len(places)), self.assertRaises(RelevanceUnavailable):
                self.client.classify(text, '', places)
        self.session.post.assert_not_called()
        self.session.post.return_value = decisions({'Flood': float('nan')})
        with self.assertRaises(RelevanceUnavailable):
            self.client.classify(TEXT, '', [place()])

    def test_semantic_pipeline_bypasses_both_keyword_dependencies(self):
        model_output = {**place(), 'locations': ['Austin Texas'], 'sentiment': 'Neutral', 'polarity': 0}
        self.session.post.return_value = decisions({'Flood': .96})
        with patch.dict(os.environ, ENV), \
                patch.object(entry, 'get_relevance_client', return_value=self.client), \
                patch.object(entry, 'screen_candidates') as gate, \
                patch.object(entry, 'extract_entities', return_value=model_output) as model:
            posts = entry.filter_posts(pd.DataFrame([{'text': TEXT}]), prefilter=True)
        gate.assert_not_called()
        model.assert_called_once_with(TEXT, rule_gate=False)
        self.assertEqual(posts.iloc[0]['disasters'], ['Flood'])
        self.assertEqual(posts.iloc[0]['classification_mode'], 'jev')

    def test_old_model_service_cannot_silently_discard_semantic_posts(self):
        session = Mock()
        session.post.return_value = Mock(json=lambda: {'disasters': [], 'skipped_non_crisis': True})
        with patch.object(entry, 'model_session', return_value=session), self.assertRaisesRegex(ValueError, 'needs updating'):
            entry.extract_entities(TEXT, rule_gate=False)

    def test_failure_keeps_durable_post_queued(self):
        self.session.post.side_effect = requests.Timeout()
        post = {**demo.create_mock_post(TEXT)[0], 'created_at': pd.Timestamp.now(tz='UTC').isoformat()}
        batch = entry.CollectedPosts([post], receipt='b' * 32)
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), \
                patch.dict(os.environ, {**ENV, 'CRISIS_PIPELINE_MODE': 'live'}), \
                patch.object(entry, 'get_scraped_posts', return_value=batch), \
                patch.object(entry, 'get_relevance_client', return_value=self.client), \
                patch.object(entry, 'extract_entities', return_value={**place(), 'locations': ['Austin Texas']}), \
                patch.object(entry, 'acknowledge_posts') as ack:
            entry.main(output_dir=directory)
            self.assertEqual(read_status(directory)['relevance_errors'], 1)
            self.assertFalse((Path(directory) / 'filtered_posts.csv').exists())
            ack.assert_not_called()

    def test_mode_validation_and_original_fixture_remain_offline(self):
        with patch.dict(os.environ, CRISIS_CLASSIFICATION_MODE='unsupported'), self.assertRaises(ValueError):
            classification_mode()
        with patch.dict(os.environ, CRISIS_CLASSIFICATION_MODE='jev', CRISIS_RELEVANCE_MODE='off'), self.assertRaises(ValueError):
            classification_mode()
        with patch.dict(os.environ, ENV), redirect_stdout(io.StringIO()), \
                patch.object(entry, 'get_relevance_client') as client:
            posts, _ = demo.process_test_tweet(fixture=True)
            self.assertEqual(posts.iloc[0]['disasters'], "['Flood']")
            client.assert_not_called()
        self.assertEqual(os.environ.get('CRISIS_CLASSIFICATION_MODE', 'rules'), 'rules')


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ('supabase', 'spacy', 'spacytextblob')),
                     'requires live dependencies')
class SemanticModelEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, SUPABASE_URL='https://fixture.invalid', SUPABASE_KEY='fixture-only'), \
                patch('supabase.create_client', return_value=Mock()):
            import model_server
        cls.model = model_server

    def test_location_extraction_and_lookup_continue_without_disaster_keywords(self):
        with patch.object(self.model, 'nlp', object()), \
                patch.object(self.model, 'has_disaster_candidate', return_value=False) as gate, \
                patch.object(self.model, 'extract_ent_sent', return_value={'disasters': [], 'locations': ['Austin Texas']}) as nlp, \
                patch.object(self.model, 'standardize_row', return_value=place()) as lookup:
            http = self.model.app.test_client()
            original = http.post('/extract_entities', json={'text': TEXT}).json
            self.assertTrue(original['skipped_non_crisis'])
            gate.reset_mock()
            semantic = http.post('/extract_entities', json={'text': TEXT, 'rule_gate': False})
            self.assertEqual(semantic.status_code, 200)
            self.assertEqual(semantic.json['city'], 'Austin')
            self.assertFalse(semantic.json['rule_gate_applied'])
            gate.assert_not_called()
            nlp.assert_called_once_with(TEXT)
            lookup.assert_called_once_with({'locations': ['Austin Texas'], 'text': TEXT})

    def test_rule_gate_option_and_text_are_strictly_validated(self):
        http = self.model.app.test_client()
        for payload in [[], {'text': TEXT, 'rule_gate': 'false'}, {'text': TEXT, 'rule_gate': 0},
                        {'text': ['Flood']}, {'text': 'x' * 10001}, {'text': '  '}]:
            with self.subTest(payload=str(payload)[:30]):
                self.assertEqual(http.post('/extract_entities', json=payload).status_code, 400)


if __name__ == '__main__':
    unittest.main()
