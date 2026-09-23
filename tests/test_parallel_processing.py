"""Concurrent work must preserve decisions, delivery, and the shared API budget."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import importlib.util
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'proj-dev/app/live_demo'))
import entry  # noqa: E402
from jev_relevance import JevRelevance, RelevanceUnavailable  # noqa: E402
from pipeline_status import read_status, write_status  # noqa: E402


def post(i):
    return {'text': f'Flood {i}', 'uri': f'at://did:plc:example/app.bsky.feed.post/{i}'}


def entities(text):
    return {'disasters': ['Flood'], 'locations': ['Austin'], 'city': 'Austin', 'state': 'Texas',
            'country': 'US', 'polarity': 0, 'latitude': 30.2672, 'longitude': -97.7431}


def evaluate(client, text):
    return client.screen(text, '', [entities(text)])


def approved():
    return Mock(status_code=200, json=lambda: {'answers': {
        'candidate_0': {'type': 'boolean', 'probability': .95}}})


class ParallelProcessingTests(unittest.TestCase):
    def test_four_workers_overlap_but_progress_and_output_stay_ordered(self):
        barrier = threading.Barrier(4)
        active = peak = 0
        lock = threading.Lock()
        def model(text):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait(timeout=3)
            with lock:
                active -= 1
            return entities(text)
        progress, main_thread = [], threading.get_ident()
        rows = pd.DataFrame([post(i) for i in range(8)])
        with patch.object(entry, 'extract_entities', side_effect=model), \
                patch.object(entry, 'get_relevance_client', return_value=None):
            result = entry.filter_posts(rows, workers=4,
                on_progress=lambda n, errors: progress.append((n, errors, threading.get_ident())))
        self.assertEqual(peak, 4)
        self.assertEqual(list(result.uri), list(rows.uri))
        self.assertEqual(progress, [(i, 0, main_thread) for i in range(1, 9)])

    def test_bulk_gate_skips_only_explicit_negatives_and_preserves_every_candidate(self):
        rows = pd.DataFrame([post(i) for i in range(100)])
        stats, progress = {}, Mock()
        mask = [i in (3, 89) for i in range(100)]
        with patch.object(entry, 'screen_candidates', return_value=mask) as screen, \
                patch.object(entry, 'extract_entities', side_effect=entities) as model, \
                patch.object(entry, 'get_relevance_client', return_value=None):
            result = entry.filter_posts(rows, progress, stats, workers=4, prefilter=True)
        screen.assert_called_once_with(list(rows.text))
        self.assertEqual(model.call_count, 2)
        self.assertEqual(list(result.uri), [post(3)['uri'], post(89)['uri']])
        self.assertEqual(stats['rule_skipped'], 98)
        progress.assert_called_with(100, 0)

    def test_malformed_gate_cannot_silently_drop_posts(self):
        session = Mock()
        for payload in ({'candidates': []}, {'candidates': [1]}, {'candidates': [None]}):
            with self.subTest(payload=payload), patch.object(entry, 'model_session', return_value=session):
                session.post.return_value = Mock(status_code=200, json=lambda: payload)
                with self.assertRaises(ValueError):
                    entry.screen_candidates(['Flood'])
        session.post.return_value = Mock(status_code=404)
        with patch.object(entry, 'model_session', return_value=session):
            self.assertEqual(entry.screen_candidates(['Flood', 'Hello']), [True, True])

    def test_coalesced_progress_still_finishes_after_duplicate_rows_are_removed(self):
        progress = Mock()
        rows = pd.DataFrame([post(0), post(0), post(1), post(2)])
        with patch.object(entry, 'extract_entities', side_effect=entities), \
                patch.object(entry, 'get_relevance_client', return_value=None), \
                patch.object(entry.time, 'monotonic', return_value=100):
            result = entry.filter_posts(rows, progress, workers=4, progress_interval=.25)
        self.assertEqual(len(result), 3)
        self.assertEqual(progress.call_count, 2)
        progress.assert_called_with(3, 0)

    def test_retry_reuses_successful_posts_but_reanalyzes_failed_posts(self):
        rows, cache = pd.DataFrame([post(0), post(1)]), {}
        calls, failing = [], True
        def model(text):
            calls.append(text)
            if failing and text == post(1)['text']:
                raise requests.Timeout()
            return entities(text)
        with redirect_stdout(io.StringIO()), patch.object(entry, 'extract_entities', side_effect=model), \
                patch.object(entry, 'get_relevance_client', return_value=None):
            stats = {}
            result = entry.filter_posts(rows, relevance_stats=stats, workers=4, completed=cache)
            self.assertEqual(len(result), 1)
            self.assertEqual(stats['model_errors'], 1)
            failing = False
            result = entry.filter_posts(rows, workers=4, completed=cache)
        self.assertEqual(len(result), 2)
        self.assertEqual(calls.count(post(0)['text']), 1)
        self.assertEqual(calls.count(post(1)['text']), 2)

    def test_failed_geocoding_is_not_cached_as_a_completed_nonmatch(self):
        cache, stats = {}, {}
        with redirect_stdout(io.StringIO()), \
                patch.object(entry, 'extract_entities', return_value={**entities(''), 'location_status': 'error'}), \
                patch.object(entry, 'get_relevance_client', return_value=None):
            self.assertTrue(entry.filter_posts(pd.DataFrame([post(0)]), completed=cache,
                                              relevance_stats=stats, workers=4).empty)
        self.assertEqual(cache, {})
        self.assertEqual(stats['model_errors'], 1)

    def test_jev_calls_overlap_with_two_slots_and_an_atomic_total_cap(self):
        active = peak = 0
        lock = threading.Lock()
        def send(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.04)
            with lock:
                active -= 1
            return approved()
        session = Mock(post=Mock(side_effect=send))
        client = JevRelevance('fixture-key', max_calls=3, session=session)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(evaluate, client, f'post-{i}') for i in range(8)]
            successes = 0
            for future in futures:
                try:
                    self.assertEqual(len(future.result()), 1)
                    successes += 1
                except RelevanceUnavailable:
                    pass
        self.assertEqual(peak, 2)
        self.assertEqual(successes, 3)
        self.assertEqual(client.calls, 3)
        self.assertEqual(session.post.call_count, 3)

    def test_identical_inflight_jev_requests_share_one_decision(self):
        start, sent, release = threading.Barrier(4), threading.Event(), threading.Event()
        def send(*args, **kwargs):
            sent.set()
            self.assertTrue(release.wait(3))
            return approved()
        session = Mock(post=Mock(side_effect=send))
        client = JevRelevance('fixture-key', session=session)
        def run():
            start.wait(3)
            return evaluate(client, 'same post')
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(run) for _ in range(4)]
            try:
                self.assertTrue(sent.wait(3))
            finally:
                release.set()
            results = [future.result() for future in futures]
        self.assertEqual(session.post.call_count, 1)
        self.assertTrue(all(result == results[0] for result in results))

    def test_request_start_pacing_is_shared_by_all_workers(self):
        starts, lock = [], threading.Lock()
        def send(*args, **kwargs):
            with lock:
                starts.append(time.monotonic())
            return approved()
        client = JevRelevance('fixture-key', session=Mock(post=Mock(side_effect=send)), min_interval=.04)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: evaluate(client, f'post-{i}'), range(6)))
        self.assertTrue(all(len(result) == 1 for result in results))
        self.assertEqual(len(starts), 6)
        self.assertTrue(all(b - a >= .035 for a, b in zip(starts, starts[1:])))

    def test_cooldown_does_not_repeat_context_or_model_work_and_resumes_afterward(self):
        client = JevRelevance('fixture-key', session=Mock())
        with TemporaryDirectory() as directory, \
                patch.object(entry, 'get_relevance_client', return_value=client), \
                patch.object(entry, 'get_scraped_posts', return_value=[]) as collect, \
                patch.object(entry, 'filter_posts') as analyze, \
                patch.object(entry, 'acknowledge_posts') as ack, \
                patch('jev_relevance.time.monotonic', return_value=100), redirect_stdout(io.StringIO()):
            write_status(directory, phase='error', last_error='Retrying.', batch_receipt='pending')
            client.retry_after = 130
            entry.main(output_dir=directory)
            entry.main(output_dir=directory)
            collect.assert_not_called()
            analyze.assert_not_called()
            ack.assert_not_called()
            self.assertEqual(read_status(directory)['batch_receipt'], 'pending')
            self.assertEqual(read_status(directory)['phase'], 'error')
            client.retry_after = 0
            entry.main(output_dir=directory)
            collect.assert_called_once()
            self.assertEqual(read_status(directory)['phase'], 'waiting')

    def test_failure_cooldown_applies_to_waiting_jev_workers(self):
        start = threading.Barrier(2)
        def fail(*args, **kwargs):
            start.wait(3)
            raise requests.Timeout('fixture-key')
        session = Mock(post=Mock(side_effect=fail))
        client = JevRelevance('fixture-key', session=session)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(evaluate, client, f'post-{i}') for i in range(4)]
            for future in futures:
                with self.assertRaises(RelevanceUnavailable) as raised:
                    future.result()
                self.assertNotIn('fixture-key', str(raised.exception))
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(client._inflight, {})

    def test_exhausted_budget_keeps_receipt_pending_and_reports_the_actual_reason(self):
        client = JevRelevance('fixture-key', max_calls=1, session=Mock())
        client.calls = 1
        batch = entry.CollectedPosts([post(0)], receipt='a' * 32)
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), \
                patch.dict(os.environ, CRISIS_PIPELINE_MODE='demo', CRISIS_PROCESSING_WORKERS='4'), \
                patch.object(entry, 'get_scraped_posts', return_value=batch), \
                patch.object(entry, 'extract_entities', side_effect=entities), \
                patch.object(entry, 'get_relevance_client', return_value=client), \
                patch.object(entry, 'acknowledge_posts') as ack:
            entry.main(output_dir=directory)
            status = read_status(directory)
        ack.assert_not_called()
        client.session.post.assert_not_called()
        self.assertEqual(status['jev_calls'], 1)
        self.assertEqual(status['jev_max_calls'], 1)
        self.assertIn('configured request limit', status['last_error'])

    def test_uncapped_provider_failure_keeps_receipt_without_false_limit_warning(self):
        session = Mock(post=Mock(return_value=Mock(status_code=429)))
        client = JevRelevance('fixture-key', max_calls=0, session=session)
        client.calls = 200
        batch = entry.CollectedPosts([post(0)], receipt='b' * 32)
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), \
                patch.dict(os.environ, CRISIS_PIPELINE_MODE='demo', CRISIS_PROCESSING_WORKERS='4'), \
                patch.object(entry, 'get_scraped_posts', return_value=batch), \
                patch.object(entry, 'extract_entities', side_effect=entities), \
                patch.object(entry, 'get_relevance_client', return_value=client), \
                patch.object(entry, 'acknowledge_posts') as ack:
            entry.main(output_dir=directory)
            entry.main(output_dir=directory)
            status = read_status(directory)
        ack.assert_not_called()
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(status['jev_calls'], 201)
        self.assertEqual(status['jev_max_calls'], 0)
        self.assertGreater(status['jev_cooldown_seconds'], 0)
        self.assertEqual(status['last_error'], 'Analysis unavailable. Keeping this batch queued for retry.')


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ('spacy', 'spacytextblob', 'supabase')),
                     'requires live dependencies')
class ModelConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, SUPABASE_URL='https://fixture.invalid', SUPABASE_KEY='fixture-only'), \
                patch('supabase.create_client', return_value=Mock()):
            import model_server
        cls.model = model_server

    def test_batch_gate_contract_and_bounds(self):
        app = self.model.app.test_client()
        with patch.object(self.model, 'nlp', object()), \
                patch.object(self.model, 'has_disaster_candidate', side_effect=lambda text: text == 'Flood'):
            self.assertEqual(app.post('/disaster_candidates', json={'texts': ['hello', 'Flood']}).json,
                             {'candidates': [False, True]})
            for data in ({'texts': []}, {'texts': ['Flood'] * 101}, {'texts': [None]},
                         {'texts': ['x' * 10001]}, []):
                self.assertEqual(app.post('/disaster_candidates', json=data).status_code, 400)
        with patch.object(self.model, 'nlp', None):
            self.assertEqual(app.post('/disaster_candidates', json={'texts': ['Flood']}).status_code, 503)

    def test_transformer_work_never_runs_concurrently(self):
        import entity_extraction
        active = peak = 0
        lock = threading.Lock()
        def infer(text):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.01)
            with lock:
                active -= 1
            return {'text': text}
        with patch.object(entity_extraction, '_extract_ent_sent', side_effect=infer), \
                ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(entity_extraction.extract_ent_sent, ['a', 'b', 'c', 'd']))
        self.assertEqual(peak, 1)
        self.assertEqual(results, [{'text': text} for text in ['a', 'b', 'c', 'd']])


if __name__ == '__main__':
    unittest.main()
