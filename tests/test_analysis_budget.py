"""Interactive waits stop without changing background pacing or caching failures."""

from concurrent.futures import Future
import hashlib
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'proj-dev/app/live_demo'))
from analysis_budget import AnalysisTimeout, analysis_deadline, http_timeout, remaining_time, request_slot  # noqa: E402
from jev_relevance import JevRelevance, MODEL, RelevanceUnavailable  # noqa: E402


class AnalysisBudgetTests(unittest.TestCase):
    def test_nested_budget_restores_context_and_bounds_total_socket_wait(self):
        with patch('analysis_budget.time.monotonic', return_value=100):
            with analysis_deadline(12):
                self.assertEqual(remaining_time(), 12)
                with analysis_deadline(2):
                    self.assertLessEqual(sum(http_timeout((3, 6))), 2)
                self.assertEqual(remaining_time(), 12)
                with analysis_deadline(30):
                    self.assertEqual(remaining_time(), 12)
        self.assertIsNone(remaining_time())
        self.assertEqual(http_timeout((3, 6)), (3, 6))
        self.assertEqual(http_timeout(10), 10)

    def test_expiration_propagates_and_resets_context(self):
        now = [100.]
        with patch('analysis_budget.time.monotonic', side_effect=lambda: now[0]):
            with self.assertRaises(AnalysisTimeout):
                with analysis_deadline(12):
                    now[0] = 113
        self.assertIsNone(remaining_time())

    def test_pacing_beyond_budget_returns_without_sleep_call_or_stale_inflight(self):
        client = JevRelevance('fixture-secret', session=Mock(), min_interval=1)
        client._next_request_at = 130
        with patch('analysis_budget.time.monotonic', return_value=100), \
                patch('jev_relevance.time.sleep') as sleep, analysis_deadline(12):
            with self.assertRaises(AnalysisTimeout):
                client._evaluate({}, {})
        sleep.assert_not_called()
        client.session.post.assert_not_called()
        self.assertEqual(client.calls, 0)
        self.assertEqual(client.cache, {})
        self.assertEqual(client._inflight, {})
        self.assertTrue(client._slots.acquire(blocking=False))
        self.assertTrue(client._slots.acquire(blocking=False))
        client._slots.release()
        client._slots.release()

    def test_provider_cooldown_is_still_honored(self):
        client = JevRelevance('fixture-secret', session=Mock())
        client.retry_after = 190
        with patch('analysis_budget.time.monotonic', return_value=100), analysis_deadline(12):
            with self.assertRaises(RelevanceUnavailable):
                client._evaluate({}, {})
        client.session.post.assert_not_called()
        self.assertEqual(client.retry_after, 190)

    def test_busy_semaphore_times_out_without_releasing_another_worker(self):
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        with self.assertRaises(AnalysisTimeout), analysis_deadline(.02):
            with request_slot(semaphore):
                self.fail('Busy worker should not be acquired')
        self.assertFalse(semaphore.acquire(blocking=False))
        semaphore.release()

    def test_waiter_times_out_without_canceling_or_removing_shared_request(self):
        client = JevRelevance('fixture-secret', session=Mock())
        payload = {'model': MODEL, 'state': {}, 'questions': {}}
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        future = client._inflight[key] = Future()
        # Catch outside the context: its exit also checks elapsed time.
        with self.assertRaises(AnalysisTimeout), analysis_deadline(.02):
            client._evaluate({}, {})
        self.assertIs(client._inflight[key], future)
        self.assertFalse(future.cancelled())
        client.session.post.assert_not_called()

    def test_brief_503_recovers_once_after_cooldown_and_caches_real_result(self):
        now = [100.]
        sent_at = []
        answers = {'decision': {'type': 'boolean', 'probability': .95}}
        responses = iter([Mock(status_code=503, headers={}),
                          Mock(status_code=200, json=lambda: {'answers': answers})])

        def send(*args, **kwargs):
            sent_at.append(now[0])
            return next(responses)

        client = JevRelevance('fixture-secret', session=Mock(), min_interval=1)
        client.session.post.side_effect = send
        with patch('analysis_budget.time.monotonic', side_effect=lambda: now[0]), \
                patch('jev_relevance.time.sleep', side_effect=lambda delay: now.__setitem__(0, now[0] + delay)), \
                analysis_deadline(12):
            self.assertEqual(client._evaluate({}, {'decision': {'type': 'boolean'}}), answers)
            self.assertEqual(client._evaluate({}, {'decision': {'type': 'boolean'}}), answers)
        self.assertEqual(sent_at, [100, 102])
        self.assertEqual(client.calls, 2)
        self.assertEqual(client.diagnostics()['jev_successful_calls'], 1)
        self.assertEqual(client.diagnostics()['jev_request_interval_seconds'], 1)
        self.assertEqual(client._next_request_at, 103)

    def test_interactive_success_does_not_retain_bulk_request_spacing(self):
        client = JevRelevance('fixture-secret', session=Mock(), min_interval=1)
        client._request_interval = 30
        client.session.post.return_value = Mock(status_code=200, json=lambda: {'answers': {}})
        with patch('analysis_budget.time.monotonic', return_value=100), analysis_deadline(12):
            client._evaluate({}, {})
        self.assertEqual(client._next_request_at, 101)

    def test_repeated_503_stops_after_one_retry_and_never_caches_failure(self):
        now = [100.]
        client = JevRelevance('fixture-secret', session=Mock())
        client.session.post.return_value = Mock(status_code=503, headers={})
        with patch('analysis_budget.time.monotonic', side_effect=lambda: now[0]), \
                patch('jev_relevance.time.sleep', side_effect=lambda delay: now.__setitem__(0, now[0] + delay)), \
                self.assertRaises(RelevanceUnavailable) as raised, analysis_deadline(12):
            client._evaluate({}, {})
        self.assertEqual(raised.exception.kind, 'http_503')
        self.assertEqual(client.session.post.call_count, 2)
        self.assertEqual(client.cache, {})
        self.assertEqual(client._inflight, {})

    def test_long_retry_after_or_short_budget_returns_without_retry(self):
        for seconds, retry_after in ((12, '90'), (5, '4')):
            client = JevRelevance('fixture-secret', session=Mock())
            client.session.post.return_value = Mock(status_code=503, headers={'Retry-After': retry_after})
            with patch('analysis_budget.time.monotonic', return_value=100), \
                    patch('jev_relevance.time.sleep') as sleep, \
                    self.assertRaises(RelevanceUnavailable), analysis_deadline(seconds):
                client._evaluate({}, {})
            sleep.assert_not_called()
            self.assertEqual(client.session.post.call_count, 1)

    def test_rate_limit_and_access_failures_never_auto_retry(self):
        for status in (401, 402, 403, 429):
            client = JevRelevance('fixture-secret', session=Mock())
            client.session.post.return_value = Mock(status_code=status, headers={})
            with self.assertRaises(RelevanceUnavailable) as raised, analysis_deadline(12):
                client._evaluate({}, {})
            self.assertEqual(raised.exception.kind, f'http_{status}')
            self.assertEqual(client.session.post.call_count, 1)

    def test_background_503_has_no_new_automatic_retry(self):
        client = JevRelevance('fixture-secret', session=Mock())
        client.session.post.return_value = Mock(status_code=503, headers={})
        with self.assertRaises(RelevanceUnavailable):
            client._evaluate({}, {})
        self.assertEqual(client.session.post.call_count, 1)


if __name__ == '__main__':
    unittest.main()
