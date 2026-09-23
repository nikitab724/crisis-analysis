"""Reply context stays bounded, source-linked, and separate from the target claim."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'proj-dev/app/live_demo'))
import entry
import post_context as context
from crisis_classification import semantic_candidate, DISASTER_DEFINITIONS
from jev_relevance import JevRelevance

URI = 'at://did:plc:parent/app.bsky.feed.post/abc'
ENV = {'CRISIS_CLASSIFICATION_MODE': 'jev', 'CRISIS_RELEVANCE_MODE': 'jev'}


class ContextTests(unittest.TestCase):
    def test_collector_metadata_retains_only_parent_root_and_link_text(self):
        record = {'reply': {'parent': {'uri': URI}, 'root': {'uri': URI}}, 'embed': {
            '$type': 'app.bsky.embed.external', 'external': {'title': 'Water rescue',
            'description': 'At the lake.', 'uri': 'http://127.0.0.1/private'}}}
        saved = context.record_metadata(record)
        self.assertEqual(saved['reply_parent_uri'], URI)
        self.assertEqual(saved['link_title'], 'Water rescue')
        self.assertNotIn('127.0.0.1', str(saved))

    def test_parent_and_root_deduplicate_and_profile_location_is_not_included(self):
        post = {'uri': URI, 'author': {'did': 'did:plc:other', 'displayName': 'From Texas'},
                'record': {'text': 'Flood in Maine.', 'createdAt': '2026-09-23T12:00:00Z'}}
        with patch.object(context, 'fetch_public_posts', return_value=[post]) as fetch:
            result = context.context_for_post({'text': 'Here too.', 'author': 'did:plc:target',
                      'reply_parent_uri': URI, 'reply_root_uri': URI})
        fetch.assert_called_once_with((URI,))
        self.assertFalse(result[0]['same_author'])
        self.assertNotIn('From Texas', str(result))
        self.assertEqual(result[0]['uri'], URI)

    def test_malformed_optional_metadata_cannot_stop_collection(self):
        for record in [{'reply': 'invalid', 'embed': []}, {'reply': {'parent': 3}},
                       {'embed': {'$type': 'app.bsky.embed.external', 'external': 'invalid'}},
                       {'embed': {'$type': 'app.bsky.embed.recordWithMedia', 'media': 3}}]:
            self.assertTrue(all(value == '' for value in context.record_metadata(record).values()))

    def test_arbitrary_urls_and_nan_do_not_trigger_fetches(self):
        with patch.object(context, 'fetch_public_posts') as fetch:
            self.assertEqual(context.context_for_post({'reply_parent_uri': 'http://localhost/private',
                             'reply_root_uri': float('nan')}), [])
        fetch.assert_not_called()

    def test_failed_context_lookup_is_not_cached_or_treated_as_completed(self):
        cache, stats = {}, {}
        with patch.dict(os.environ, ENV), patch.object(entry, 'get_relevance_client', return_value=Mock()), \
                patch.object(entry, 'context_for_post', side_effect=requests.Timeout()), \
                patch.object(entry, 'extract_entities') as model:
            result = entry.filter_posts(pd.DataFrame([{'text': 'Flood here too.', 'uri': URI}]),
                                        relevance_stats=stats, completed=cache)
        self.assertTrue(result.empty)
        self.assertEqual(cache, {})
        self.assertEqual(stats['model_errors'], 1)
        model.assert_not_called()

    def test_original_post_is_displayed_and_context_reaches_location_and_classifier(self):
        contextual = [{'kind': 'reply_context', 'uri': URI, 'text': 'Austin Texas.'}]
        model_output = {'disasters': [], 'locations': ['Austin'], 'city': 'Austin', 'state': 'Texas',
                        'country': 'US', 'latitude': 30.2, 'longitude': -97.7}
        reviewer = Mock()
        reviewer.classify.side_effect = lambda text, timestamp, rows, **kwargs: [
            {**row, 'disasters': ['Power Outage']} for row in rows]
        with patch.dict(os.environ, ENV), patch.object(entry, 'get_relevance_client', return_value=reviewer), \
                patch.object(entry, 'context_for_post', return_value=contextual), \
                patch.object(entry, 'extract_entities', return_value=model_output) as model:
            result = entry.filter_posts(pd.DataFrame([{'text': 'Our electricity went out.', 'uri': URI}]))
        self.assertIn('Austin Texas.', model.call_args.args[0])
        self.assertEqual(result.iloc[0]['text'], 'Our electricity went out.')
        self.assertEqual(result.iloc[0]['context_sources'], URI)
        self.assertEqual(reviewer.classify.call_args.kwargs['context'], contextual)

    def test_extended_candidates_cover_user_examples_but_never_assign_labels(self):
        for text in ['The streets in Houston are underwater.', 'A teacher and a child drowned.',
                     'Electricity has gone off twice today.', 'We are flickering too.',
                     'A flood of compliments.', 'The canyon is prone to flood.']:
            self.assertTrue(semantic_candidate(text), text)
        self.assertFalse(semantic_candidate('Good morning everyone.'))
        self.assertIn('Drowning', DISASTER_DEFINITIONS)
        self.assertIn('Power Outage', DISASTER_DEFINITIONS)

    def test_link_card_can_make_a_post_a_candidate_without_fetching_article(self):
        reviewer = Mock()
        with patch.dict(os.environ, {**ENV, 'CRISIS_CANDIDATE_FILTER': 'expanded'}), \
                patch.object(entry, 'get_relevance_client', return_value=reviewer), \
                patch.object(entry, 'extract_entities', return_value={'locations': [], 'disasters': []}) as model:
            entry.filter_posts(pd.DataFrame([{'text': 'This is so sad.', 'link_title': 'Child drowned at lake'}]),
                               prefilter=True)
        self.assertIn('Child drowned', model.call_args.args[0])

    def test_jev_context_is_structured_and_instructions_bind_target_claim(self):
        session = Mock()
        session.post.return_value = Mock(status_code=200, json=lambda: {'answers': {
            f'type_{i}': {'type': 'boolean', 'probability': .01} for i in range(len(DISASTER_DEFINITIONS))}})
        client = JevRelevance('test', session=session)
        client.classify_text('Here too.', context=[{'kind': 'reply_context', 'text': 'Flood elsewhere.'}])
        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['state']['post_text'], 'Here too.')
        self.assertIn('Do not copy an unrelated parent event', payload['questions']['type_0']['instructions'])


if __name__ == '__main__':
    unittest.main()
