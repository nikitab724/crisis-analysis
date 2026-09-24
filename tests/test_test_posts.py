"""Real test posts never publish, save, acknowledge, or substitute fixture decisions."""

from pathlib import Path
from copy import deepcopy
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'proj-dev/app/live_demo'))
import test_posts as testing  # noqa: E402
import dash_client as dashboard  # noqa: E402
from analysis_budget import AnalysisTimeout  # noqa: E402

TOKEN = 'test-only-token-not-a-real-secret-123456789'
RECORD = {'country': 'US', 'city': 'Houston', 'state': 'Texas', 'disasters': ['Flood'],
          'latitude': 29.7604, 'longitude': -95.3698}


class TestPostTests(unittest.TestCase):
    def setUp(self):
        with testing._cache_lock:
            testing._result_cache.clear()
        http = patch.object(testing, '_remote_http', threading.local())
        http.start()
        self.addCleanup(http.stop)

    def test_endpoint_auth_validation_and_backpressure(self):
        analyzer = Mock(return_value={'status': 'mapped', 'records': [RECORD], 'analysis': 'live'})
        app = Flask('test-posts')
        testing.register_test_endpoint(app, analyzer)
        with patch.dict(testing.os.environ, {'CRISIS_TEST_API_TOKEN': TOKEN}), app.test_client() as client:
            self.assertEqual(client.post('/demo/analyze', json={'text': 'Flood'}).status_code, 401)
            auth = {'Authorization': 'Bearer ' + TOKEN}
            for text in ('', ' ' * 4, None, [], 3, 'x' * 1001):
                self.assertEqual(client.post('/demo/analyze', json={'text': text}, headers=auth).status_code, 400)
            self.assertEqual(client.post('/demo/analyze', data='x' * 9000, headers=auth).status_code, 413)
            with testing._slot:
                self.assertEqual(client.post('/demo/analyze', json={'text': 'Flood'}, headers=auth).status_code, 429)
            analyzer.assert_not_called()
            self.assertEqual(client.post('/demo/analyze', json={'text': 'Flood'}, headers=auth).json['analysis'], 'live')
            analyzer.side_effect = RuntimeError('private provider response')
            response = client.post('/demo/analyze', json={'text': 'Flood'}, headers=auth)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('private', response.get_data(as_text=True))

    def test_real_worker_is_reused_without_writing_or_queueing(self):
        relevance = Mock()
        with patch('entry.analyze_post', return_value=([RECORD], {}, 0)) as analyze, \
                patch('entry.save_csv', side_effect=AssertionError('Must not save')), \
                patch('entry.acknowledge_posts', side_effect=AssertionError('Must not ack')), \
                patch('entry.get_scraped_posts', side_effect=AssertionError('Must not collect')), \
                patch('jev_relevance.get_relevance_client', return_value=relevance):
            result = testing.analyze_locally('Flood in Houston, Texas.')
        self.assertEqual(result['status'], 'mapped')
        self.assertEqual(result['records'], [RECORD])
        self.assertTrue(analyze.call_args.kwargs['classify'])
        self.assertEqual(analyze.call_args.args[1]['text'], 'Flood in Houston, Texas.')
        relevance.classify_text.assert_not_called()

    def test_unmapped_and_irrelevant_remain_distinct(self):
        relevance = Mock()
        with patch('entry.analyze_post', return_value=([], {}, 0)), \
                patch('jev_relevance.get_relevance_client', return_value=relevance):
            relevance.classify_text.return_value = {'disasters': ['Flood']}
            self.assertEqual(testing.analyze_locally('Flood in Portland.')['status'], 'unmapped')
            relevance.classify_text.return_value = {'disasters': []}
            self.assertEqual(testing.analyze_locally('Coffee time.')['status'], 'skipped')

    def test_ambiguous_houston_explains_state_needed_without_plotting(self):
        # Exercise the real worker with controlled NLP/Jev responses. Lowercase
        # Houston is already recognized; ambiguity must not become a Texas guess.
        import entry
        choices = [{'mention': 'houston', 'candidates': [
            RECORD, {**RECORD, 'state': 'Mississippi', 'latitude': 33.89845, 'longitude': -88.99923}]}]
        entities = {'locations': ['houston'], 'disasters': [], 'location_status': 'ambiguous',
                    'location_choices': choices, 'unresolved_locations': ['houston']}
        relevance = Mock()
        relevance.choose_locations.return_value = []
        relevance.classify_text.return_value = {'disasters': ['Flood']}
        with patch.object(entry, 'extract_entities', return_value=entities) as extract, \
                patch('jev_relevance.get_relevance_client', return_value=relevance):
            result = testing.analyze_locally('so much rain in houston people are struggling')
        self.assertEqual(result['status'], 'unmapped')
        self.assertEqual(result['records'], [])
        self.assertIn('“houston” matches multiple US places', result['message'])
        self.assertIn('Add a state, such as “Houston, Texas”', result['message'])
        extract.assert_called_once_with('so much rain in houston people are struggling', rule_gate=False)

    def test_guidance_distinguishes_missing_unresolved_and_unlinked_places(self):
        self.assertIn('No place name was detected', testing.location_guidance({'locations': []}))
        self.assertIn('could not be matched', testing.location_guidance({'locations': ['Nowhere']}))
        self.assertIn('multiple US locations', testing.location_guidance({'location_status': 'ambiguous'}))
        self.assertIn('could not be linked', testing.location_guidance({'locations': ['Houston'], 'resolved_locations': 1}))

    def test_resolved_choice_does_not_leave_stale_ambiguity_guidance(self):
        diagnostics = {'locations': ['Houston'], 'unresolved_locations': [], 'resolved_locations': 1,
                       'location_choices': [{'mention': 'Houston', 'candidates': [RECORD]}]}
        self.assertNotIn('multiple', testing.location_guidance(diagnostics))

    def test_analysis_error_never_becomes_a_negative_or_fixture(self):
        for result in [([], {}, 1), ([], {'location_errors': 1}, 0), ([], {'relevance_errors': 1}, 0)]:
            with patch('entry.analyze_post', return_value=result), \
                    patch('jev_relevance.get_relevance_client', return_value=Mock()):
                with self.assertRaises(testing.AnalysisUnavailable):
                    testing.analyze_locally('Flood in Houston.')

    def test_resolved_negative_is_not_classified_twice(self):
        import entry
        relevance = Mock()
        relevance.classify.return_value = []
        entities = {**RECORD, 'locations': ['Houston'], 'disasters': [], 'location_status': 'matched'}
        with patch.object(entry, 'extract_entities', return_value=entities), \
                patch('jev_relevance.get_relevance_client', return_value=relevance):
            result = testing.analyze_locally('I like the weather in Houston, Texas.')
        self.assertEqual(result['status'], 'skipped')
        self.assertIn('No current crisis could be linked', result['message'])
        relevance.classify.assert_called_once()
        relevance.classify_text.assert_not_called()

    def test_timeout_releases_endpoint_slot_and_is_not_a_negative(self):
        import entry
        relevance = Mock()
        relevance.choose_locations.side_effect = AnalysisTimeout('private pacing detail')
        entities = {'locations': ['San Mateo'], 'location_choices': [{'mention': 'San Mateo'}]}
        app = Flask('timed-test-posts')
        testing.register_test_endpoint(app)
        with patch.dict(testing.os.environ, {'CRISIS_TEST_API_TOKEN': TOKEN}), \
                patch.object(entry, 'extract_entities', return_value=entities), \
                patch('jev_relevance.get_relevance_client', return_value=relevance), app.test_client() as client:
            response = client.post('/demo/analyze', json={'text': 'flood in san mateo'},
                                   headers={'Authorization': 'Bearer ' + TOKEN})
            self.assertEqual(response.status_code, 504)
            self.assertEqual(response.json['code'], 'analysis_timeout')
            self.assertNotIn('private', response.get_data(as_text=True))
            with patch.object(entry, 'analyze_post', return_value=([RECORD], {}, 0)):
                retry = client.post('/demo/analyze', json={'text': 'Flood in Houston, Texas'},
                                    headers={'Authorization': 'Bearer ' + TOKEN})
            self.assertEqual(retry.status_code, 200)
        relevance.classify_text.assert_not_called()

    def test_unresolved_second_place_still_gets_global_classification(self):
        relevance = Mock()
        relevance.classify_text.return_value = {'disasters': ['Flood']}

        def analyze(*args, diagnostics, **kwargs):
            diagnostics.update(classification_completed=True, unresolved_locations=['San Mateo'])
            return [], {}, 0

        with patch('entry.analyze_post', side_effect=analyze), \
                patch('jev_relevance.get_relevance_client', return_value=relevance):
            result = testing.analyze_locally('Austin is dry; flood in San Mateo.')
        self.assertEqual(result['status'], 'unmapped')
        relevance.classify_text.assert_called_once()

    def test_remote_request_is_bounded_and_secrets_stay_server_side(self):
        env = {'LIVE_DASHBOARD_URL': 'https://test-backend.example', 'CRISIS_TEST_API_TOKEN': TOKEN}
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {'status': 'mapped', 'records': [RECORD], 'analysis': 'live'}
        with patch.dict(testing.os.environ, env), patch.object(testing.requests, 'Session') as factory:
            factory.return_value = session
            self.assertEqual(testing.analyze_remote('Flood')['status'], 'mapped')
            self.assertFalse(session.post.call_args.kwargs['allow_redirects'])
            self.assertEqual(session.post.call_args.kwargs['timeout'], (3, 16))
            self.assertEqual(session.post.call_args.kwargs['json'], {'text': 'Flood'})
            session.post.return_value.status_code = 503
            with self.assertRaises(testing.AnalysisUnavailable):
                testing.analyze_remote('Another flood')
            session.post.return_value.status_code = 504
            with self.assertRaisesRegex(testing.AnalysisUnavailable, 'taking too long'):
                testing.analyze_remote('Another flood')

    def test_provider_failure_is_identified_at_every_analysis_stage(self):
        import entry
        from jev_relevance import RelevanceUnavailable
        cases = [
            ('choose_locations', {'locations': ['Houston'], 'location_choices': [{'mention': 'Houston'}]}),
            ('classify', {**RECORD, 'locations': ['Houston'], 'location_status': 'matched'}),
            ('classify_text', {'locations': []}),
        ]
        for method, entities in cases:
            client = Mock()
            getattr(client, method).side_effect = RelevanceUnavailable('private response body', kind='http_503')
            with self.subTest(stage=method), patch.object(entry, 'extract_entities', return_value=entities), \
                    patch('jev_relevance.get_relevance_client', return_value=client), \
                    self.assertRaises(testing.AnalysisUnavailable) as raised:
                testing.analyze_locally('Flood in Houston')
            self.assertEqual(raised.exception.code, 'jev_busy')
            self.assertNotIn('private', str(raised.exception))

    def test_endpoint_sends_only_allowlisted_failure_codes_and_copy(self):
        analyzer = Mock(side_effect=testing.AnalysisUnavailable('private details', code='jev_busy'))
        app = Flask('provider-failure-test')
        testing.register_test_endpoint(app, analyzer)
        with patch.dict(testing.os.environ, {'CRISIS_TEST_API_TOKEN': TOKEN}), app.test_client() as client:
            response = client.post('/demo/analyze', json={'text': 'Flood'},
                                   headers={'Authorization': 'Bearer ' + TOKEN})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {'code': 'jev_busy', 'error': testing.ERROR_MESSAGES['jev_busy']})

    def test_remote_preserves_known_error_kind_without_forwarding_provider_body(self):
        env = {'LIVE_DASHBOARD_URL': 'https://test-backend.example', 'CRISIS_TEST_API_TOKEN': TOKEN}
        session = Mock()
        session.post.return_value.status_code = 503
        with patch.dict(testing.os.environ, env), patch.object(testing.requests, 'Session') as factory:
            factory.return_value = session
            for code in ('jev_busy', 'jev_access', 'location_unavailable', 'unknown', ['invalid']):
                session.post.return_value.json.return_value = {'code': code, 'error': 'private provider body'}
                with self.assertRaises(testing.AnalysisUnavailable) as raised:
                    testing.analyze_remote('Flood')
                self.assertNotIn('private', str(raised.exception))
                if isinstance(code, str) and code in testing.ERROR_MESSAGES:
                    self.assertEqual(str(raised.exception), testing.ERROR_MESSAGES[code])
                else:
                    self.assertIn('test backend', str(raised.exception))

    def test_real_result_cache_expires_and_isolates_mutable_results(self):
        env = {'LIVE_DASHBOARD_URL': 'https://test-backend.example', 'CRISIS_TEST_API_TOKEN': TOKEN}
        session = Mock()
        decision = {'status': 'mapped', 'records': [RECORD], 'analysis': 'live'}
        session.post.return_value.status_code = 200
        session.post.return_value.json.side_effect = lambda: deepcopy(decision)
        now = [100.]
        with patch.dict(testing.os.environ, env), patch.object(testing, 'remote_session', return_value=session), \
                patch.object(testing.time, 'monotonic', side_effect=lambda: now[0]):
            first = testing.analyze_remote('Flood')
            first['records'][0]['city'] = 'Mutated'
            now[0] = 159
            second = testing.analyze_remote('Flood')
            self.assertEqual(second['records'][0]['city'], 'Houston')
            second['records'].clear()
            self.assertEqual(len(testing.analyze_remote('Flood')['records']), 1)
            self.assertEqual(session.post.call_count, 1)
            now[0] = 160
            testing.analyze_remote('Flood')
            self.assertEqual(session.post.call_count, 2)

    def test_cache_keys_preserve_text_and_backend_identity(self):
        env = {'LIVE_DASHBOARD_URL': 'https://test-backend.example', 'CRISIS_TEST_API_TOKEN': TOKEN}
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {'status': 'mapped', 'records': [RECORD], 'analysis': 'live'}
        with patch.dict(testing.os.environ, env), patch.object(testing, 'remote_session', return_value=session):
            testing.analyze_remote('Flood')
            testing.analyze_remote('flood')
            testing.os.environ['LIVE_DASHBOARD_URL'] = 'https://new-backend.example'
            testing.analyze_remote('Flood')
            testing.os.environ['CRISIS_TEST_API_TOKEN'] = TOKEN + '-rotated'
            testing.analyze_remote('Flood')
            self.assertEqual(session.post.call_count, 4)

    def test_failures_and_malformed_responses_are_never_cached(self):
        env = {'LIVE_DASHBOARD_URL': 'https://test-backend.example', 'CRISIS_TEST_API_TOKEN': TOKEN}
        session = Mock()
        with patch.dict(testing.os.environ, env), patch.object(testing, 'remote_session', return_value=session):
            for status, body in ((503, {'code': 'jev_busy'}), (200, {'analysis': 'predefined'})):
                session.post.return_value.status_code = status
                session.post.return_value.json.return_value = body
                with self.assertRaises(testing.AnalysisUnavailable):
                    testing.analyze_remote('Flood')
            self.assertEqual(testing._result_cache, {})
            session.post.return_value.status_code = 200
            session.post.return_value.json.return_value = {'status': 'mapped', 'records': [RECORD], 'analysis': 'live'}
            testing.analyze_remote('Flood')
            testing.analyze_remote('Flood')
            self.assertEqual(session.post.call_count, 3)

    def test_result_cache_has_a_fixed_memory_bound(self):
        env = {'LIVE_DASHBOARD_URL': 'https://test-backend.example', 'CRISIS_TEST_API_TOKEN': TOKEN}
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {'status': 'mapped', 'records': [RECORD], 'analysis': 'live'}
        with patch.dict(testing.os.environ, env), patch.object(testing, 'remote_session', return_value=session), \
                patch.object(testing, 'RESULT_CACHE_SIZE', 2):
            for text in ('first', 'second', 'third'):
                testing.analyze_remote(text)
            self.assertEqual(len(testing._result_cache), 2)
            testing.analyze_remote('first')
            self.assertEqual(session.post.call_count, 4)

    def test_backend_connection_is_reused_only_within_its_worker_thread(self):
        sessions = []
        with patch.object(testing.requests, 'Session', side_effect=lambda: Mock()) as factory:
            first = testing.remote_session()
            self.assertIs(first, testing.remote_session())
            worker = threading.Thread(target=lambda: sessions.append(testing.remote_session()))
            worker.start()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertIsNot(first, sessions[0])
            self.assertFalse(first.trust_env)
            self.assertFalse(sessions[0].trust_env)
            self.assertEqual(factory.call_count, 2)

    def test_test_marker_does_not_change_dataset_counts(self):
        from sample_feed import load_samples
        with patch.object(dashboard, 'PIPELINE_MODE', 'sample'), patch.object(dashboard, 'SAMPLES', load_samples()):
            base = dashboard.update_crisis_map(0)
            result = {'records': [RECORD], 'analysis': 'live', 'status': 'mapped'}
            with_test = dashboard.update_crisis_map(0, None, result)
            self.assertEqual(len(with_test.data), len(base.data) + 1)
            self.assertEqual(with_test.data[-1].name, 'Your test')
            self.assertEqual(with_test.data[-1].marker.symbol, 'diamond')
            self.assertEqual(with_test.data[-1].lat[0], 29.7604)
            self.assertEqual(len(dashboard.load_dashboard_posts()), 14)

    def test_error_is_visible_and_clears_previous_marker(self):
        with patch.object(testing, 'analyze_remote', side_effect=testing.AnalysisUnavailable('Try again.')):
            result, feedback = dashboard.run_test_post('Flood')
            self.assertIsNone(result)
            self.assertIn('Try again.', str(feedback))


if __name__ == '__main__':
    unittest.main()
