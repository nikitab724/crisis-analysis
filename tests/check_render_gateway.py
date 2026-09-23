"""Check a public gateway, or rehearse the Render launcher against a live backend."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import requests

ROOT = Path(__file__).resolve().parents[1]


def check(base):
    session = requests.Session()
    session.trust_env = False
    assert session.get(base + '/_proxy/health', timeout=20).json()['mode'] == 'proxy'
    assert session.get(base + '/health', timeout=20).json() == {'mode': 'live', 'status': 'healthy'}
    page = session.get(base + '/', timeout=20)
    page.raise_for_status()
    assets = sorted(set(re.findall(r'(?:src|href)="(/[^\"]+)"', page.text)))
    assert assets

    def check_asset(path):
        response = requests.get(base + path, timeout=25)
        response.raise_for_status()
        assert response.content, path

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(check_asset, assets))
    layout = session.get(base + '/_dash-layout', timeout=20)
    layout.raise_for_status()
    assert 'Past 24 hours' in layout.text and 'Sample data' not in layout.text
    session.get(base + '/_dash-dependencies', timeout=20).raise_for_status()
    interval = {'id': 'interval-component', 'property': 'n_intervals', 'value': 0}
    outputs = ['state-dropdown.options', 'crisis-map.figure',
               'posts-table.children', 'pipeline-activity.children']
    for output in outputs:
        component, prop = output.split('.')
        inputs = ([{'id': 'state-dropdown', 'property': 'value', 'value': None}]
                  if component == 'posts-table' else []) + [interval]
        response = session.post(base + '/_dash-update-component', timeout=25, json={
            'output': output, 'outputs': {'id': component, 'property': prop},
            'inputs': inputs, 'state': [], 'changedPropIds': ['interval-component.n_intervals'],
        })
        response.raise_for_status()
        assert component in response.json()['response']
    activity = session.get(base + '/activity', timeout=20).json()
    assert activity['mode'] == 'live' and activity['relevance_mode'] == 'jev'
    assert session.post(base + '/extract_entities', json={'text': 'test'}, timeout=20).status_code == 404
    print(f'PASS: live health, {len(assets)} browser assets, layout, four callbacks, Jev activity, and blocked model route.')
    return {'url': base, 'assets_checked': len(assets), 'callbacks': outputs, 'activity': activity}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--url', help='An already deployed gateway URL')
    group.add_argument('--backend-url', help='Rehearse the Render launcher locally against this live HTTPS origin')
    args = parser.parse_args()
    if args.url:
        result = check(args.url.rstrip('/'))
    else:
        with TemporaryDirectory(prefix='crisis-gateway-check-') as temporary:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, LIVE_DASHBOARD_URL=args.backend_url, PORT=str(port),
                       PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', ''))
            with open(Path(temporary) / 'gateway.log', 'w') as log:
                process = subprocess.Popen(['bash', 'scripts/start_demo.sh'], cwd=ROOT, env=env,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    base = f'http://127.0.0.1:{port}'
                    for _ in range(50):
                        if process.poll() is not None:
                            raise RuntimeError('Gateway launcher exited before becoming ready')
                        try:
                            if requests.get(base + '/_proxy/health', timeout=1).status_code == 200:
                                break
                        except requests.RequestException:
                            pass
                        time.sleep(.2)
                    else:
                        raise RuntimeError('Gateway launcher did not become ready')
                    result = check(base)
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=20)
    output = ROOT / '.demo-hosted/render-gateway-check.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
