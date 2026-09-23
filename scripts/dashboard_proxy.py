"""Forward the public Dash UI to one configured live dashboard.

Render runs this small gateway; NLP, ingestion, CSVs, and credentials stay on
the original host. This is not a general-purpose URL or model API proxy.
"""

import os
import threading
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request
import requests

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
READ_PATHS = {'/', '/health', '/activity', '/_dash-layout', '/_dash-dependencies',
              '/_favicon.ico', '/favicon.ico'}
ASSET_PREFIXES = ('/assets/', '/_dash-component-suites/')
RESPONSE_HEADERS = {'content-type', 'cache-control', 'etag', 'last-modified', 'vary'}
UNAVAILABLE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crisis Analysis · Temporarily unavailable</title>
<style>body{margin:0;background:#f8fafc;color:#182230;font:16px/1.6 system-ui,sans-serif}
main{max-width:520px;margin:15vh auto;padding:32px}h1{font-size:28px;line-height:1.2}
p{color:#526174}a{color:#1763cf;text-underline-offset:4px}</style></head>
<body><main><p>Crisis Analysis</p><h1>The live demo is temporarily unavailable.</h1>
<p>The computer processing live reports may be offline or restarting. Please try again shortly.</p>
<a href="/">Try again</a></main></body></html>"""


def create_app(backend_url=None, http_request=None):
    backend_url = backend_url if backend_url is not None else os.environ.get('LIVE_DASHBOARD_URL', '')
    parsed = urlsplit(backend_url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('LIVE_DASHBOARD_URL must be an HTTPS origin with no credentials, path, or query.')
    backend_url = backend_url.rstrip('/')
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 256 * 1024
    connections = threading.local()

    def unavailable():
        if request.path == '/':
            response = Response(UNAVAILABLE_HTML, status=503, mimetype='text/html')
        else:
            response = jsonify(status='unavailable', component='live_dashboard')
            response.status_code = 503
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Retry-After'] = '15'
        return response

    @app.get('/_proxy/health')
    def proxy_health():
        # Diagnostic only. Render's /_dash-layout readiness still checks the live app.
        return {'status': 'healthy', 'mode': 'proxy'}

    @app.route('/', defaults={'path': ''}, methods=['GET', 'HEAD', 'POST'])
    @app.route('/<path:path>', methods=['GET', 'HEAD', 'POST'])
    def forward(path):
        route = '/' + path
        if any(segment in ('.', '..') for segment in route.split('/')) or '\\' in route:
            return jsonify(error='Not found'), 404
        if route == '/_dash-update-component':
            if request.method != 'POST':
                return jsonify(error='Method not allowed'), 405
            if not request.is_json:
                return jsonify(error='JSON required'), 415
        elif route in READ_PATHS or route.startswith(ASSET_PREFIXES):
            if request.method not in ('GET', 'HEAD'):
                return jsonify(error='Method not allowed'), 405
        else:
            return jsonify(error='Not found'), 404
        if request.host.casefold() == parsed.netloc.casefold():
            return unavailable()  # Prevent a configuration pointing back to this service.
        headers = {'Accept-Encoding': 'identity', 'User-Agent': 'crisis-dashboard-proxy/1.0'}
        if request.content_type:
            headers['Content-Type'] = request.content_type
        for name in ('Accept', 'If-None-Match', 'If-Modified-Since'):
            if name in request.headers:
                headers[name] = request.headers[name]
        upstream = None
        session = None
        try:
            send = http_request
            if send is None:
                session = getattr(connections, 'session', None)
                if session is None:
                    session = requests.Session()
                    session.trust_env = False  # Avoid macOS proxy discovery in a forked worker.
                    connections.session = session
                session.cookies.clear()  # Reuse transport, never cross-visitor cookies.
                send = session.request
            upstream = send(request.method, backend_url + route, params=list(request.args.items(multi=True)),
                            data=request.get_data() if request.method == 'POST' else None,
                            headers=headers, timeout=(3, 15), allow_redirects=False, stream=True)
            if upstream.status_code >= 500 or (300 <= upstream.status_code < 400 and upstream.status_code != 304):
                return unavailable()
            content = bytearray()
            for chunk in upstream.iter_content(chunk_size=65536):
                if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                    return unavailable()
                content.extend(chunk)
            response_headers = {key: value for key, value in upstream.headers.items()
                                if key.lower() in RESPONSE_HEADERS}
            if not route.startswith(ASSET_PREFIXES):
                response_headers['Cache-Control'] = 'no-store'
            return Response(bytes(content), status=upstream.status_code, headers=response_headers)
        except requests.RequestException:
            # Never include provider bodies, URLs, request headers, or secrets in errors.
            if session is not None:
                session.close()
                connections.session = None
            return unavailable()
        finally:
            if upstream is not None:
                upstream.close()
            if session is not None:
                session.cookies.clear()

    return app
