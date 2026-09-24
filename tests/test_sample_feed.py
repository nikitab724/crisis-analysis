"""Saved public posts retain their real results without live services or writes."""

import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "proj-dev/app/live_demo"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "scripts"))

import dash_client as dashboard  # noqa: E402
from sample_feed import load_samples, mapped_posts, source_url  # noqa: E402
from export_demo_posts import export_posts  # noqa: E402


class SavedFeedTests(unittest.TestCase):
    def setUp(self):
        self.samples = load_samples()

    def test_snapshot_contains_original_posts_and_all_saved_locations(self):
        self.assertEqual(len(self.samples), 453)
        self.assertEqual(len({p['uri'] for p in self.samples}), 453)
        self.assertEqual(len(mapped_posts(self.samples)), 586)
        self.assertEqual(self.samples[-1]['text'], 'Truck into housing authority \n\nSpokane, Washington \n\n#CarIntoBuilding')
        self.assertTrue(any(len(p['records']) > 1 for p in self.samples))
        self.assertTrue(any(not r['city'] for p in self.samples for r in p['records']))
        self.assertTrue(any(len(r['disasters']) > 1 for p in self.samples for r in p['records']))
        self.assertTrue(all(p['created_at'].startswith('2026-09-23') for p in self.samples))

    def test_export_preserves_text_and_results_without_private_fields_or_duplicates(self):
        row = {'uri': 'at://did:plc:example/app.bsky.feed.post/one', 'text': 'flood here\n& there <3',
               'created_at': '2026-09-23T05:00:00Z', 'city': 'Austin', 'state': 'Texas', 'country': 'US',
               'disasters': "['Flood', 'Drowning']", 'latitude': '30.2672', 'longitude': '-97.7431',
               'private_internal_field': 'must-not-be-exported'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'posts.csv'
            with path.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=row)
                writer.writeheader()
                writer.writerows([row, row, {**row, 'city': '', 'latitude': '', 'longitude': ''},
                                 {**row, 'country': 'CA'}, {**row, 'uri': 'synthetic-test'}])
            original = path.read_bytes()
            data = export_posts(path)
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(data['posts']), 1)
        post = data['posts'][0]
        self.assertEqual(post['text'], row['text'])
        self.assertEqual(post['created_at'], row['created_at'])
        self.assertEqual(len(post['records']), 2)
        self.assertEqual(post['records'][0]['disasters'], ['Flood', 'Drowning'])
        self.assertIsNone(post['records'][1]['latitude'])
        self.assertEqual(data['excluded_rows'], 2)
        self.assertNotIn('must-not-be-exported', json.dumps(data))

    def test_feed_is_newest_first_paginated_and_filters_any_saved_location(self):
        before = json.dumps(self.samples, sort_keys=True)
        with patch.object(dashboard, 'SAMPLES', self.samples):
            first = dashboard.render_sample_feed(None)
            self.assertEqual(len(first.children), 50)
            self.assertEqual(self.samples[-1]['text'], first.children[0].children.children[1].children)
            self.assertEqual(len(dashboard.render_sample_feed(None, 100).children), 100)
            self.assertEqual(len(dashboard.render_sample_feed(None, 10000).children), 453)
            state = self.samples[-1]['records'][0]['state']
            selected = dashboard.saved_posts_for_state(state)
            self.assertTrue(all(any(r['state'] == state for r in p['records']) for p in selected))
            rendered = str(dashboard.render_sample_feed(None))
            self.assertIn('https://bsky.app/profile/', rendered)
            self.assertIn('Sep 23, 2026', rendered)
            for label in ('Skipped', 'Sample social post', 'Location unclear', 'Transportation Accident'):
                self.assertNotIn(label, rendered)
        self.assertEqual(before, json.dumps(self.samples, sort_keys=True))

    def test_map_counts_all_locations_independently_of_feed_pagination(self):
        points = dashboard.map_points_from_posts(mapped_posts(self.samples))
        self.assertEqual(sum(p['count'] for p in points), 586)
        self.assertTrue(any(p['precision'] == 'State centroid (approximate)' for p in points))
        with patch.object(dashboard, 'SAMPLES', self.samples):
            dashboard.render_sample_feed(None, 50)
            self.assertEqual(len(mapped_posts(self.samples)), 586)

    def test_snapshot_ignores_live_files_services_and_expiry(self):
        with patch.object(dashboard, 'PIPELINE_MODE', 'sample'), \
                patch.object(dashboard, 'SAMPLES', self.samples), \
                patch.object(dashboard.pd, 'read_csv', side_effect=AssertionError('Read live data')), \
                patch.object(dashboard, 'recent_posts', side_effect=AssertionError('Expired saved data')), \
                patch.object(dashboard.backend_http, 'get', side_effect=AssertionError('Called backend')):
            self.assertEqual(len(dashboard.load_dashboard_posts()), 586)
            self.assertIsNone(dashboard.update_activity(0))
            self.assertEqual(sum(row[0] for trace in dashboard.update_crisis_map(0).data for row in trace.customdata), 586)
            with dashboard.server.test_client() as client:
                self.assertEqual(client.get('/health').json, {'status': 'healthy', 'mode': 'sample', 'posts': 453})
                self.assertEqual(client.get('/activity').json['analysis'], 'saved')

    def test_source_links_stay_on_bluesky(self):
        for uri in ('https://example.com', 'javascript:alert(1)', 'at://did:plc:a/other/one'):
            with self.assertRaises(ValueError):
                source_url(uri)
        self.assertEqual(source_url('at://did:plc:a/app.bsky.feed.post/abc'),
                         'https://bsky.app/profile/did:plc:a/post/abc')

    def test_dashboard_callbacks_without_network_or_live_files(self):
        script = '''
from unittest.mock import patch
import requests
with patch.object(requests.Session, 'request', side_effect=AssertionError('Network forbidden')):
    import dash_client as d
    with d.server.test_client() as client:
        layout = client.get('/_dash-layout').get_data(as_text=True)
        assert 'Saved posts' in layout
        assert 'replay-play' not in layout and 'replay-clock' not in layout
        assert 'feed-more' in layout and 'test-submit' in layout
        assert client.get('/health').json['posts'] == 453
        response = client.post('/_dash-update-component', json={
            'output': 'crisis-map.figure',
            'outputs': {'id': 'crisis-map', 'property': 'figure'},
            'inputs': [
                {'id': 'interval-component', 'property': 'n_intervals', 'value': 0},
                {'id': 'test-result', 'property': 'data', 'value': None}],
            'state': [], 'changedPropIds': ['interval-component.n_intervals']})
        assert response.status_code == 200, response.get_data(as_text=True)
        traces = response.json['response']['crisis-map']['figure']['data']
        assert sum(row[0] for trace in traces for row in trace['customdata']) == 586
        for limit, count in [(50, 50), (100, 100), (500, 453)]:
            response = client.post('/_dash-update-component', json={
                'output': 'posts-table.children',
                'outputs': {'id': 'posts-table', 'property': 'children'},
                'inputs': [
                    {'id': 'state-dropdown', 'property': 'value', 'value': None},
                    {'id': 'interval-component', 'property': 'n_intervals', 'value': 0},
                    {'id': 'feed-limit', 'property': 'data', 'value': limit}],
                'state': [], 'changedPropIds': ['feed-limit.data']})
            assert response.status_code == 200, response.get_data(as_text=True)
            rows = response.json['response']['posts-table']['children']['props']['children']
            assert len(rows) == count
        output = '..feed-limit.data...feed-more.style..'
        def page(trigger, limit, state=None):
            response = client.post('/_dash-update-component', json={
                'output': output,
                'outputs': [{'id': 'feed-limit', 'property': 'data'}, {'id': 'feed-more', 'property': 'style'}],
                'inputs': [{'id': 'feed-more', 'property': 'n_clicks', 'value': 1},
                           {'id': 'state-dropdown', 'property': 'value', 'value': state}],
                'state': [{'id': 'feed-limit', 'property': 'data', 'value': limit}],
                'changedPropIds': [trigger]})
            assert response.status_code == 200, response.get_data(as_text=True)
            return response.json['response']
        assert page('feed-more.n_clicks', 50)['feed-limit']['data'] == 100
        end = page('feed-more.n_clicks', 450)
        assert end['feed-limit']['data'] == 453 and end['feed-more']['style'] == {'display': 'none'}
        reset = page('state-dropdown.value', 400, 'Washington')
        assert 0 < reset['feed-limit']['data'] <= 50
'''
        env = {**os.environ, 'CRISIS_PIPELINE_MODE': 'sample', 'CRISIS_DATA_DIR': '/nonexistent-demo-data',
               'CRISIS_TEST_BACKEND': '0', 'PYTHONPATH': str(APP)}
        result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
