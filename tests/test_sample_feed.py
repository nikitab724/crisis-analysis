"""The interview replay is deterministic, isolated, and explicit about fixtures."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "proj-dev/app/live_demo"
sys.path.insert(0, str(APP))

import dash_client as dashboard  # noqa: E402
from sample_feed import load_samples, mapped_posts, visible_samples  # noqa: E402


class SampleFeedTests(unittest.TestCase):
    def setUp(self):
        self.samples = load_samples()

    def test_mixed_dataset_and_expected_outcomes(self):
        self.assertEqual(len(self.samples), 24)
        self.assertEqual(len(mapped_posts(self.samples)), 14)
        self.assertEqual(sum(p['outcome'] == 'skipped' for p in self.samples), 9)
        self.assertEqual(sum(p['outcome'] == 'unmapped' for p in self.samples), 1)
        samples = {p['id']: p for p in self.samples}
        self.assertEqual(samples['houston-underwater']['disaster'], 'Flood')
        self.assertIn('Houston, Texas', samples['houston-underwater']['context'])
        for name in ('sports', 'history', 'negation', 'pandemic-joke', 'overseas', 'canyon-risk'):
            self.assertEqual(samples[name]['outcome'], 'skipped')
        self.assertEqual(samples['portland-ambiguous']['outcome'], 'unmapped')

    def test_replay_progression_and_sessions_are_independent(self):
        original = json.dumps(self.samples, sort_keys=True)
        for cursor in range(25):
            visible = visible_samples(self.samples, {'cursor': cursor})
            posts = mapped_posts(self.samples, {'cursor': cursor})
            self.assertEqual(len(visible), cursor)
            self.assertEqual(len(posts), sum(p['outcome'] == 'mapped' for p in visible))
        self.assertEqual(len(visible_samples(self.samples, {'cursor': 0})), 0)
        self.assertEqual(len(visible_samples(self.samples)), 24)
        self.assertEqual(json.dumps(self.samples, sort_keys=True), original)
        self.assertEqual(mapped_posts(self.samples).to_csv(index=False), mapped_posts(load_samples()).to_csv(index=False))

    def test_untrusted_cursor_is_bounded(self):
        for state, count in [({'cursor': -20}, 0), ({'cursor': 1000000}, 24),
                             ({'cursor': 'bad'}, 24), ({'cursor': True}, 24), ([], 24)]:
            self.assertEqual(len(visible_samples(self.samples, state)), count)

    def test_existing_map_aggregation_uses_resolved_places_and_real_counts(self):
        points = dashboard.map_points_from_posts(mapped_posts(self.samples))
        self.assertEqual(sum(p['count'] for p in points), 14)
        self.assertEqual(len(points), 12)
        locations = {p['location']: p for p in points}
        self.assertEqual(locations['Austin, Texas']['count'], 2)
        self.assertEqual(locations['Houston, Texas']['count'], 2)
        self.assertIn('Portland, Maine', locations)
        self.assertIn('Portland, Oregon', locations)
        self.assertNotIn('Portland', locations)

    def test_dashboard_does_not_read_live_data_or_call_services(self):
        with patch.object(dashboard, 'PIPELINE_MODE', 'sample'), \
                patch.object(dashboard, 'SAMPLES', self.samples), \
                patch.object(dashboard.pd, 'read_csv', side_effect=AssertionError('Read live data')), \
                patch.object(dashboard.backend_http, 'get', side_effect=AssertionError('Called backend')):
            self.assertEqual(len(dashboard.load_dashboard_posts()), 14)
            self.assertEqual(len(dashboard.update_dropdown_options(0)), 9)
            self.assertIsNone(dashboard.update_activity(0))
            self.assertEqual(len(dashboard.update_crisis_map(0, {'cursor': 0}).data), 0)
            self.assertIn('No reports yet', str(dashboard.update_crisis_map(0, {'cursor': 0})))
            full = str(dashboard.update_table(None, 0))
            self.assertIn('questionable parking', full)
            self.assertIn('Location unclear', full)
            self.assertNotIn('https://bsky.app', full)
            texas = str(dashboard.update_table('Texas', 0))
            self.assertIn('Houston', texas)
            self.assertNotIn('Portland', texas)
            with dashboard.server.test_client() as client:
                self.assertEqual(client.get('/health').json, {'status': 'healthy', 'mode': 'sample', 'posts': 24})
                self.assertEqual(client.get('/activity').json['analysis'], 'predefined')

    def test_sample_mode_callback_wiring_without_files_or_network(self):
        script = '''
from unittest.mock import patch
import requests
with patch.object(requests.Session, 'request', side_effect=AssertionError('Network forbidden')):
    import dash_client as d
    with d.server.test_client() as client:
        layout = client.get('/_dash-layout').get_data(as_text=True)
        assert 'Synthetic posts' in layout and 'Predefined results' in layout
        assert 'replay-state' in layout and 'replay-play' in layout
        assert client.get('/health').status_code == 200
        for cursor, count in [(0, 0), (4, 2), (24, 14), (0, 0)]:
            response = client.post('/_dash-update-component', json={
                'output': 'crisis-map.figure',
                'outputs': {'id': 'crisis-map', 'property': 'figure'},
                'inputs': [
                    {'id': 'interval-component', 'property': 'n_intervals', 'value': 0},
                    {'id': 'replay-state', 'property': 'data', 'value': {'cursor': cursor}},
                    {'id': 'test-result', 'property': 'data', 'value': None}],
                'state': [], 'changedPropIds': ['replay-state.data']})
            assert response.status_code == 200, response.get_data(as_text=True)
            traces = response.json['response']['crisis-map']['figure']['data']
            assert sum(row[0] for trace in traces for row in trace['customdata']) == count
'''
        env = {**os.environ, 'CRISIS_PIPELINE_MODE': 'sample', 'CRISIS_DATA_DIR': '/nonexistent-demo-data',
               'PYTHONPATH': str(APP)}
        result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
