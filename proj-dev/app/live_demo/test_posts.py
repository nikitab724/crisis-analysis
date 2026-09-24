"""Isolated, explicit real-analysis requests for the interview dashboard."""

from datetime import datetime, timezone
from collections import OrderedDict
from copy import deepcopy
import hashlib
import hmac
import logging
import math
import os
import threading
import time
from urllib.parse import urlsplit

from flask import request
import requests
from analysis_budget import AnalysisTimeout, analysis_deadline
from us_scope import is_us_location


MAX_TEXT_LENGTH = 1000
ANALYSIS_SECONDS = 12
TIMEOUT_MESSAGE = 'Analysis is taking too long. Please try again shortly.'
ERROR_MESSAGES = {
    'jev_busy': 'Jev is temporarily unavailable. Please try again shortly.',
    'jev_access': 'Jev access needs attention. The sample replay still works.',
    'location_unavailable': 'Location analysis is temporarily unavailable. Please try again shortly.',
}
_slot = threading.BoundedSemaphore(1)
_remote_http = threading.local()
_result_cache = OrderedDict()
_cache_lock = threading.Lock()
RESULT_CACHE_SECONDS = 60
RESULT_CACHE_SIZE = 128


class AnalysisUnavailable(RuntimeError):
    def __init__(self, message, *, code=None):
        super().__init__(message)
        self.code = code


def remote_session():
    """Reuse TLS connections without sharing a mutable Session across workers."""
    if not hasattr(_remote_http, 'session'):
        _remote_http.session = requests.Session()
        _remote_http.session.trust_env = False
    return _remote_http.session


def validate_text(text):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"Enter a post of 1–{MAX_TEXT_LENGTH} characters.")
    return text.strip()


def location_guidance(diagnostics):
    """Explain why a recognized crisis was not plotted, without choosing a city."""
    if diagnostics.get('resolved_locations'):
        return 'A US location was found, but the crisis could not be linked to it. Make the incident location explicit.'
    unresolved = set(diagnostics.get('unresolved_locations') or [])
    for group in diagnostics.get('location_choices') or []:
        if group.get('mention') not in unresolved:
            continue
        candidates = group.get('candidates') or []
        examples = [f'{item["city"]}, {item["state"]}' for item in candidates
                    if is_us_location(item) and item.get('city')]
        if examples:
            return (f'“{group["mention"]}” matches multiple US places. '
                    f'Add a state, such as “{examples[0]}”, and analyze again.')
    if diagnostics.get('location_status') == 'ambiguous':
        return 'The place name matches multiple US locations. Add a city and state, then analyze again.'
    if not diagnostics.get('locations'):
        return 'No place name was detected. Add a US city and state, then analyze again.'
    return 'The place could not be matched to a supported US location. Include the city and state, then analyze again.'


def analyze_locally(text):
    """Use the live analysis worker, without its writer, queue, or acknowledgement."""
    from jev_relevance import RelevanceUnavailable

    with analysis_deadline(ANALYSIS_SECONDS):
        try:
            return _analyze_locally(text)
        except RelevanceUnavailable as exc:
            logging.getLogger(__name__).warning('Test analysis provider failure: %s', exc.kind)
            code = 'jev_access' if exc.kind in ('usage_cap', 'http_401', 'http_402', 'http_403') else 'jev_busy'
            raise AnalysisUnavailable(ERROR_MESSAGES[code], code=code) from None


def _analyze_locally(text):
    from entry import analyze_post
    from jev_relevance import get_relevance_client

    text = validate_text(text)
    client = get_relevance_client()
    if client is None:
        raise AnalysisUnavailable("Real analysis is not configured.")
    published_at = datetime.now(timezone.utc).isoformat()
    diagnostics = {}
    rows, stats, errors = analyze_post(0, {'text': text, 'created_at': published_at}, client,
                                      classify=True, diagnostics=diagnostics)
    if errors or any(stats.get(key) for key in ('model_errors', 'location_errors', 'relevance_errors')):
        logging.getLogger(__name__).warning('Test analysis unavailable: stages=%s provider=%s',
                                            stats, client.diagnostics())
        code = 'location_unavailable' if errors or stats.get('model_errors') else 'jev_busy'
        raise AnalysisUnavailable(ERROR_MESSAGES[code], code=code)
    records = []
    for row in rows[:8]:
        record = {key: row.get(key) for key in ('city', 'state', 'country', 'disasters')}
        for key in ('latitude', 'longitude'):
            value = row.get(key)
            record[key] = float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None
        records.append(record)
    if records:
        return {'status': 'mapped', 'text': text, 'records': records, 'analysis': 'live'}
    if diagnostics.get('classification_completed') and not diagnostics.get('unresolved_locations'):
        return {'status': 'skipped', 'text': text, 'records': [], 'disasters': [], 'analysis': 'live',
                'message': 'No current crisis could be linked to this US location.'}
    # Classification remains useful when a US location cannot be resolved.
    classification = client.classify_text(text, published_at)
    labels = classification['disasters']
    return {'status': 'unmapped' if labels else 'skipped', 'text': text, 'records': [],
            'disasters': labels, 'analysis': 'live',
            'message': (location_guidance(diagnostics)
                        if labels else 'No current crisis detected in this post.')}


def register_test_endpoint(server, analyzer=analyze_locally):
    """Only the explicitly enabled Mac backend accepts authenticated test calls."""
    @server.post('/demo/analyze')
    def analyze_test_post():
        token = os.environ.get('CRISIS_TEST_API_TOKEN', '')
        supplied = request.headers.get('Authorization', '')
        if len(token) < 32 or not hmac.compare_digest(supplied.encode(), f'Bearer {token}'.encode()):
            return {'error': 'Unauthorized'}, 401
        if request.content_length is None or request.content_length > 8192:
            return {'error': 'Post is too large.'}, 413
        body = request.get_json(silent=True)
        try:
            text = validate_text(body.get('text') if isinstance(body, dict) else None)
        except ValueError as exc:
            return {'error': str(exc)}, 400
        if not _slot.acquire(blocking=False):
            return {'error': 'Another test is running. Please try again shortly.'}, 429
        started = time.monotonic()
        outcome = 'unavailable'
        try:
            result = analyzer(text)
            outcome = result['status']
            return result
        except AnalysisTimeout:
            outcome = 'timeout'
            return {'error': TIMEOUT_MESSAGE, 'code': 'analysis_timeout'}, 504
        except AnalysisUnavailable as exc:
            if exc.code not in ERROR_MESSAGES:
                return {'error': 'The analyzer is unavailable. Please try again shortly.'}, 503
            outcome = exc.code
            return {'error': ERROR_MESSAGES[exc.code], 'code': exc.code}, 503
        except Exception:
            # Never return provider bodies, credentials, or internal hostnames.
            return {'error': 'The analyzer is unavailable. Please try again shortly.'}, 503
        finally:
            _slot.release()
            logging.getLogger(__name__).info('Test analysis: %s in %.2fs', outcome, time.monotonic() - started)


def analyze_remote(text):
    text = validate_text(text)
    origin = os.environ.get('LIVE_DASHBOARD_URL', '').rstrip('/')
    token = os.environ.get('CRISIS_TEST_API_TOKEN', '')
    url = urlsplit(origin)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment or len(token) < 32):
        raise AnalysisUnavailable('The test backend is offline. The sample replay still works.')
    # Cache only validated real decisions. Changes to the destination or credential
    # invalidate the key; text stays case-sensitive to preserve extraction behavior.
    cache_key = hashlib.sha256((origin + '\0' + token + '\0' + text).encode()).hexdigest()
    with _cache_lock:
        now = time.monotonic()
        for key, (expires, _) in list(_result_cache.items()):
            if expires <= now:
                del _result_cache[key]
        if cache_key in _result_cache:
            _result_cache.move_to_end(cache_key)
            return deepcopy(_result_cache[cache_key][1])
    try:
        response = remote_session().post(origin + '/demo/analyze', json={'text': text},
                                         headers={'Authorization': f'Bearer {token}'},
                                         timeout=(3, ANALYSIS_SECONDS + 4), allow_redirects=False)
        if response.status_code == 429:
            raise AnalysisUnavailable('Another test is running. Please try again shortly.')
        if response.status_code == 504:
            raise AnalysisUnavailable(TIMEOUT_MESSAGE)
        if response.status_code == 503:
            try:
                body = response.json()
            except ValueError:
                body = None
            code = body.get('code') if isinstance(body, dict) else None
            if isinstance(code, str) and code in ERROR_MESSAGES:
                raise AnalysisUnavailable(ERROR_MESSAGES[code], code=code)
        if response.status_code != 200:
            raise AnalysisUnavailable('The test backend is unavailable. Please try again shortly.')
        result = response.json()
        if (not isinstance(result, dict) or result.get('analysis') != 'live'
                or result.get('status') not in ('mapped', 'unmapped', 'skipped')
                or not isinstance(result.get('records'), list) or len(result['records']) > 8):
            raise ValueError('Invalid response')
        if result['status'] == 'mapped':
            if not result['records'] or any(
                not isinstance(row, dict) or not is_us_location(row)
                or not isinstance(row.get('disasters'), list) or not row['disasters']
                or any(not isinstance(label, str) for label in row['disasters'])
                for row in result['records']
            ):
                raise ValueError('Invalid map records')
        elif result['records'] or not isinstance(result.get('message'), str):
            raise ValueError('Invalid decision')
        with _cache_lock:
            _result_cache[cache_key] = (time.monotonic() + RESULT_CACHE_SECONDS, deepcopy(result))
            while len(_result_cache) > RESULT_CACHE_SIZE:
                _result_cache.popitem(last=False)
        return result
    except (requests.RequestException, ValueError):
        raise AnalysisUnavailable('The test backend did not respond. Please try again shortly.') from None
