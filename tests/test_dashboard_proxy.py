"""Render gateway contract: fixed upstream, working Dash callbacks, honest failures."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dashboard_proxy import create_app  # noqa: E402


class DashboardProxyTests(unittest.TestCase):
    def setUp(self):
        self.upstream = Mock(status_code=200, headers={'Content-Type': 'application/json'})
        self.upstream.iter_content.return_value = [b'{"mode":"live"}']
        self.send = Mock(return_value=self.upstream)
        self.app = create_app('https://example.trycloudflare.com/', http_request=self.send)
        self.app.testing = True
        self.client = self.app.test_client()

    def test_validates_origin_and_does_not_accept_arbitrary_urls(self):
        for url in ('', 'http://example.com', 'https://user:secret@example.com',
                    'https://example.com/path', 'https://example.com?url=other', 'https://example.com#hash'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                create_app(url)

    def test_layout_is_forwarded_without_browser_credentials(self):
        response = self.client.get('/_dash-layout?item=1&item=2', headers={
            'Authorization': 'Bearer browser-secret', 'Cookie': 'secret=value', 'X-Forwarded-Host': 'evil.invalid',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'mode': 'live'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        args, kwargs = self.send.call_args
        self.assertEqual(args, ('GET', 'https://example.trycloudflare.com/_dash-layout'))
        self.assertEqual(kwargs['params'], [('item', '1'), ('item', '2')])
        self.assertNotIn('browser-secret', str(kwargs))
        self.assertNotIn('evil.invalid', str(kwargs))
        self.assertNotIn('Cookie', kwargs['headers'])
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['timeout'], (3, 15))
        self.upstream.close.assert_called_once()

    def test_dash_post_preserves_json_body(self):
        payload = b'{"output":"crisis-map.figure","inputs":[]}'
        self.client.post('/_dash-update-component', data=payload, content_type='application/json')
        args, kwargs = self.send.call_args
        self.assertEqual(args[0], 'POST')
        self.assertEqual(kwargs['data'], payload)
        self.assertEqual(kwargs['headers']['Content-Type'], 'application/json')

    def test_assets_preserve_cache_but_drop_transfer_and_cookie_headers(self):
        self.upstream.headers = {'Content-Type': 'text/javascript', 'Content-Length': '999',
                                 'Content-Encoding': 'gzip', 'Transfer-Encoding': 'chunked',
                                 'Cache-Control': 'public, max-age=31536000', 'Set-Cookie': 'secret=value'}
        self.upstream.iter_content.return_value = [b'console.log(1)']
        response = self.client.get('/_dash-component-suites/dash/app.js')
        self.assertEqual(response.data, b'console.log(1)')
        self.assertEqual(response.headers['Content-Length'], str(len(response.data)))
        self.assertEqual(response.headers['Cache-Control'], 'public, max-age=31536000')
        for name in ('Content-Encoding', 'Transfer-Encoding', 'Set-Cookie'):
            self.assertNotIn(name, response.headers)

    def test_only_dashboard_routes_and_methods_are_forwarded(self):
        for route, method, expected in [('/extract_entities', 'post', 404), ('/.env', 'get', 404),
                                        ('/assets/../.env', 'get', 404), ('/health', 'post', 405),
                                        ('/_dash-update-component', 'get', 405),
                                        ('/_dash-update-component', 'post', 415)]:
            with self.subTest(route=route, method=method):
                self.assertEqual(getattr(self.client, method)(route).status_code, expected)
        self.send.assert_not_called()

    def test_large_requests_are_rejected_before_forwarding(self):
        response = self.client.post('/_dash-update-component', data=b'x'*(257*1024), content_type='application/json')
        self.assertEqual(response.status_code, 413)
        self.send.assert_not_called()

    def test_timeout_is_unavailable_and_never_fixture_data(self):
        self.send.side_effect = requests.Timeout('Do not expose this provider detail')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 503)
        self.assertIn('temporarily unavailable', response.text)
        self.assertNotIn('provider detail', response.text)
        self.assertNotIn('fixture', response.text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get('/activity').json['status'], 'unavailable')

    def test_upstream_errors_redirects_and_oversized_responses_fail_closed(self):
        for status in (301, 302, 307, 500, 502, 503):
            with self.subTest(status=status):
                self.upstream.status_code = status
                self.assertEqual(self.client.get('/_dash-layout').status_code, 503)
        self.upstream.status_code = 200
        with patch('dashboard_proxy.MAX_RESPONSE_BYTES', 4):
            self.assertEqual(self.client.get('/_dash-layout').status_code, 503)

    def test_self_proxy_is_rejected_and_health_diagnostic_is_local(self):
        self.assertEqual(self.client.get('/', base_url='https://example.trycloudflare.com').status_code, 503)
        self.assertEqual(self.client.get('/_proxy/health').json, {'status': 'healthy', 'mode': 'proxy'})
        self.send.assert_not_called()

    def test_reuses_worker_connection_but_clears_cookies_between_visitors(self):
        session = Mock()
        session.request.return_value = self.upstream
        with patch('dashboard_proxy.requests.Session', return_value=session) as factory:
            client = create_app('https://example.trycloudflare.com').test_client()
            self.assertEqual(client.get('/activity').status_code, 200)
            self.assertEqual(client.get('/activity').status_code, 200)
        factory.assert_called_once()
        self.assertFalse(session.trust_env)
        self.assertEqual(session.cookies.clear.call_count, 4)
        session.close.assert_not_called()

    def test_transport_failure_discards_connection_before_next_request(self):
        failing, healthy = Mock(), Mock()
        failing.request.side_effect = requests.ConnectionError()
        healthy.request.return_value = self.upstream
        with patch('dashboard_proxy.requests.Session', side_effect=[failing, healthy]) as factory:
            client = create_app('https://example.trycloudflare.com').test_client()
            self.assertEqual(client.get('/activity').status_code, 503)
            self.assertEqual(client.get('/activity').status_code, 200)
        self.assertEqual(factory.call_count, 2)
        failing.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
