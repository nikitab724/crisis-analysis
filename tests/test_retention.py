"""Live reports expire consistently by publication time, including during outages."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'proj-dev/app/live_demo'))
import dash_client as dashboard  # noqa: E402
import entry  # noqa: E402
import process_test_tweet as demo  # noqa: E402
from retention import recent_posts  # noqa: E402


def record(name, created, state='Texas'):
    return {'text': name, 'created_at': created, 'author': 'public',
            'uri': f'at://did:plc:example/app.bsky.feed.post/{name}',
            'country': 'US', 'state': state, 'city': 'Austin' if state == 'Texas' else 'Los Angeles',
            'disasters': ['Flood'], 'polarity': 0, 'sentiment': 'Neutral',
            'latitude': 30.2672, 'longitude': -97.7431}


def save_records(directory, rows):
    posts = pd.DataFrame(rows)
    entry.save_csv(posts, Path(directory) / 'filtered_posts.csv')
    entry.save_csv(entry.calculate_crisis_counts(posts), Path(directory) / 'crisis_counts.csv')


class RetentionTests(unittest.TestCase):
    def test_exact_boundary_offsets_invalid_dates_and_future_posts(self):
        now = '2026-09-23T12:00:00Z'
        frame = pd.DataFrame([
            record('boundary', '2026-09-22T12:00:00Z'),
            record('inside', '2026-09-22T12:00:00.001Z'),
            record('offset-expired', '2026-09-22T07:00:00-05:00'),
            record('offset-current', '2026-09-23T06:00:00-05:00'),
            record('now', now), record('future', '2026-09-23T12:00:01Z'),
            record('invalid', 'bad'), record('missing', None),
        ])
        self.assertEqual(list(recent_posts(frame, now)['text']), ['inside', 'offset-current', 'now'])
        self.assertTrue(recent_posts(frame.drop(columns='created_at'), now).empty)

    def test_cleanup_rebuilds_totals_and_writes_readable_empty_files(self):
        with TemporaryDirectory() as directory:
            save_records(directory, [record('old', '2026-09-21T12:00:00Z'),
                                     record('recent', '2026-09-23T11:00:00Z')])
            entry.prune_saved_reports(directory, now='2026-09-23T12:00:00Z')
            self.assertEqual(list(pd.read_csv(Path(directory) / 'filtered_posts.csv')['text']), ['recent'])
            self.assertEqual(pd.read_csv(Path(directory) / 'crisis_counts.csv')['count'].sum(), 1)
            entry.prune_saved_reports(directory, now='2026-09-24T11:00:00Z')
            self.assertTrue(pd.read_csv(Path(directory) / 'filtered_posts.csv').empty)
            counts = pd.read_csv(Path(directory) / 'crisis_counts.csv')
            self.assertTrue(counts.empty)
            self.assertEqual(list(counts.columns), entry.COUNT_COLUMNS)

    def test_cleanup_runs_when_no_new_posts_arrive_or_feed_is_down(self):
        for unavailable in (False, True):
            with self.subTest(unavailable=unavailable), TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
                save_records(directory, [record('expired', '2020-01-01T00:00:00Z')])
                with patch.dict(os.environ, {'CRISIS_PIPELINE_MODE': 'live'}), \
                        patch.object(entry, 'get_scraped_posts', return_value=[],
                                     side_effect=requests.Timeout() if unavailable else None):
                    entry.main(output_dir=directory)
                self.assertTrue(pd.read_csv(Path(directory) / 'filtered_posts.csv').empty)
                self.assertTrue(pd.read_csv(Path(directory) / 'crisis_counts.csv').empty)

    def test_expired_queued_posts_are_acknowledged_without_model_calls(self):
        batch = entry.CollectedPosts([record('expired', '2020-01-01T00:00:00Z')], receipt='a'*32)
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), \
                patch.dict(os.environ, {'CRISIS_PIPELINE_MODE': 'live'}), \
                patch.object(entry, 'get_scraped_posts', return_value=batch), \
                patch.object(entry, 'get_relevance_client', return_value=None), \
                patch.object(entry, 'extract_entities') as model, \
                patch.object(entry, 'acknowledge_posts') as ack:
            entry.main(output_dir=directory)
            model.assert_not_called()
            ack.assert_called_once_with(batch)

    def test_all_live_dashboard_surfaces_ignore_expired_records_and_stale_totals(self):
        now = pd.Timestamp.now(tz='UTC')
        with TemporaryDirectory() as directory:
            save_records(directory, [record('expired-report', (now-pd.Timedelta(hours=25)).isoformat(), 'California'),
                                     record('current-report', (now-pd.Timedelta(hours=1)).isoformat())])
            with patch.object(dashboard, 'DATA_DIR', Path(directory)), patch.object(dashboard, 'PIPELINE_MODE', 'live'):
                self.assertEqual(dashboard.update_dropdown_options(0), [{'label': 'Texas', 'value': 'Texas'}])
                self.assertNotIn('expired-report', str(dashboard.update_table(None, 0)))
                self.assertIn('current-report', str(dashboard.update_table(None, 0)))
                points = dashboard.update_crisis_map(0).data
                self.assertEqual(sum(int(row[0]) for trace in points for row in trace.customdata), 1)
                chart = dashboard.update_state_chart(0)
                self.assertEqual(list(chart.data[0].x), ['Texas'])
                self.assertEqual(list(chart.data[0].y), [1])
                self.assertEqual(dashboard.load_dashboard_counts()['count'].sum(), 1)
                self.assertIn('Location records', str(dashboard.update_stats(0)))
                # A stopped writer leaves old CSVs behind; every callback still expires them.
                with patch.object(dashboard, 'recent_posts', side_effect=lambda frame: recent_posts(frame, now+pd.Timedelta(days=2))):
                    self.assertEqual(dashboard.update_dropdown_options(0), [])
                    self.assertEqual(len(dashboard.update_crisis_map(0).data), 0)
                    self.assertTrue(all(trace.y is None or len(trace.y) == 0
                                        for trace in dashboard.update_state_chart(0).data))
                    self.assertIn('No US crisis reports', str(dashboard.update_table(None, 0)))
                    self.assertIn('No statistics available', str(dashboard.update_stats(0)))

    def test_fixed_fixture_stays_repeatable_even_with_live_environment(self):
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), \
                patch.dict(os.environ, {'CRISIS_PIPELINE_MODE': 'live'}):
            posts, counts = demo.process_test_tweet(fixture=True, output_dir=directory)
            self.assertEqual(len(posts), 1)
            self.assertEqual(counts['count'].sum(), 1)
            self.assertEqual(os.environ['CRISIS_PIPELINE_MODE'], 'live')

    def test_retry_repairs_counts_after_interrupted_expiration(self):
        with TemporaryDirectory() as directory:
            save_records(directory, [record('old', '2020-01-01T00:00:00Z')])
            save = entry.save_csv
            def fail_counts(frame, path):
                if path.name == 'crisis_counts.csv':
                    raise OSError('disk failure')
                save(frame, path)
            with patch.object(entry, 'save_csv', side_effect=fail_counts), self.assertRaises(OSError):
                entry.prune_saved_reports(directory)
            entry.prune_saved_reports(directory)
            self.assertTrue(pd.read_csv(Path(directory) / 'crisis_counts.csv').empty)


if __name__ == '__main__':
    unittest.main()
