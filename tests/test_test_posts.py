"""Real test posts never publish, save, acknowledge, or substitute fixture decisions."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'proj-dev/app/live_demo'))
import test_posts as testing  # noqa: E402
import dash_client as dashboard  # noqa: E402

TOKEN = 'test-only-token-not-a-real-secret-123456789'
RECORD = {'country': 'US', 'city': 'Houston', 'state': 'Texas', 'disasters': ['Flood'],
          'latitude': 29.7604, 'longitude': -95.3698}


class TestPostTests(unittest.TestCase):
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

    def test_analysis_error_never_becomes_a_negative_or_fixture(self):
        for result in [([], {}, 1), ([], {'location_errors': 1}, 0), ([], {'relevance_errors': 1}, 0)]:
            with patch('entry.analyze_post', return_value=result), \
                    patch('jev_relevance.get_relevance_client', return_value=Mock()):
                with self.assertRaises(testing.AnalysisUnavailable):
                    testing.analyze_locally('Flood in Houston.')

    def test_remote_request_is_bounded_and_secrets_stay_server_side(self):
        env = {'LIVE_DASHBOARD_URL': 'https://test-backend.example', 'CRISIS_TEST_API_TOKEN': TOKEN}
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {'status': 'mapped', 'records': [RECORD], 'analysis': 'live'}
        with patch.dict(testing.os.environ, env), patch.object(testing.requests, 'Session') as factory:
            factory.return_value.__enter__.return_value = session
            self.assertEqual(testing.analyze_remote('Flood')['status'], 'mapped')
            self.assertFalse(session.post.call_args.kwargs['allow_redirects'])
            self.assertEqual(session.post.call_args.kwargs['timeout'], (3, 45))
            self.assertEqual(session.post.call_args.kwargs['json'], {'text': 'Flood'})
            session.post.return_value.status_code = 503
            with self.assertRaises(testing.AnalysisUnavailable):
                testing.analyze_remote('Flood')

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
