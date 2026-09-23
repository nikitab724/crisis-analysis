"""Check the real multi-process startup using a local Supabase HTTP substitute.

Requires requirements-live.txt and the built model. No real database, credentials,
or Bluesky traffic is used. Only gazetteer HTTP responses are substituted.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
from urllib.parse import parse_qs, urlsplit

import psutil
import requests

ROOT = Path(__file__).resolve().parents[1]
database_unavailable = Event()
database_slow = Event()
queries = []


class GazetteerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path != "/rest/v1/gazetteer":
            self.send_error(404)
            return
        if database_slow.is_set():
            time.sleep(6)
            return
        query = parse_qs(parsed.query)
        queries.append(query)
        state = query.get("featureCode") == ["eq.ADM1"]
        row = {"name": "Texas" if state else "Austin", "featureCode": "ADM1" if state else "PPL",
               "stateCode": "TX", "countryCode": "US", "latitude": 31.4757 if state else 30.2672,
               "longitude": -99.3312 if state else -97.7431, "alternate_list": ",austin,",
               "population": 1000000}
        failed = database_unavailable.is_set()
        payload = json.dumps({"code": "TEST", "message": "Simulated database outage",
                              "details": None, "hint": None} if failed else [row]).encode()
        self.send_response(503 if failed else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_healthy(url, process):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"Supervisor exited early: {process.returncode}")
        try:
            response = requests.get(url + "/health", timeout=6)
            if response.status_code == 200:
                assert response.json() == {"status": "healthy", "mode": "demo"}
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise AssertionError("Dashboard never became healthy")


def callback(url, output, inputs):
    component, prop = output.split(".")
    response = requests.post(url + "/_dash-update-component", timeout=10, json={
        "output": output, "outputs": {"id": component, "property": prop},
        "inputs": inputs, "state": [], "changedPropIds": ["interval-component.n_intervals"],
    })
    response.raise_for_status()
    return response.json()["response"][component][prop]


def main():
    with TemporaryDirectory(prefix="crisis-runtime-check-") as directory:
        temporary = Path(directory)
        sentinel = temporary / "existing-data"
        sentinel.mkdir()
        (sentinel / "filtered_posts.csv").write_text("preserve existing data\n")
        with ThreadingHTTPServer(("127.0.0.1", 0), GazetteerHandler) as database:
            thread = Thread(target=database.serve_forever, daemon=True)
            thread.start()
            env = dict(os.environ, SUPABASE_URL=f"http://127.0.0.1:{database.server_port}",
                       SUPABASE_KEY="sb_secret_local_test_only", PORT=str(free_port()),
                       MODEL_PORT=str(free_port()), CRISIS_DATA_DIR=str(sentinel),
                       CRISIS_RELEVANCE_MODE="off", AI_GATEWAY_API_KEY="")
            base = f"http://127.0.0.1:{env['PORT']}"
            descendants = []
            with (temporary / "runtime.log").open("w+") as log:
                process = subprocess.Popen([sys.executable, "scripts/run_pipeline.py", "--mode", "demo"],
                                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    wait_healthy(base, process)
                    descendants = psutil.Process(process.pid).children(recursive=True)
                    layout = requests.get(base + "/_dash-layout", timeout=10)
                    layout.raise_for_status()
                    assert "Sample data" in layout.text
                    assert "FIXTURE DEMO" not in layout.text
                    model_base = f"http://127.0.0.1:{env['MODEL_PORT']}"
                    texts = ['Flood in Austin Texas.', 'A quiet afternoon in Austin Texas.']
                    def extract(text):
                        response = requests.post(model_base + '/extract_entities', json={'text': text}, timeout=15)
                        response.raise_for_status()
                        return response.json()
                    originals = list(map(extract, texts))
                    screening = requests.post(model_base + '/disaster_candidates',
                                              json={'texts': texts * 4}, timeout=15)
                    screening.raise_for_status()
                    assert screening.json()['candidates'] == [True, False] * 4
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        assert list(pool.map(extract, texts * 4)) == originals * 4
                    print('PASS: real-model batch screening and concurrent requests preserve serial outputs.')
                    interval = [{"id": "interval-component", "property": "n_intervals", "value": 0}]
                    options = callback(base, "state-dropdown.options", interval)
                    assert options == [{"label": "Texas", "value": "Texas"}]
                    crisis_map = callback(base, "crisis-map.figure", interval)
                    assert crisis_map["data"][0]["name"] == "Flood"
                    table = callback(base, "posts-table.children", [
                        {"id": "state-dropdown", "property": "value", "value": "Texas"}, *interval])
                    assert "Flood in Austin Texas." in json.dumps(table)
                    assert crisis_map["data"][0]["customdata"][0][0] == 1
                    assert "Austin, Texas" in json.dumps(table)
                    assert "Example" in json.dumps(table)
                    assert callback(base, "pipeline-activity.children", interval) is None
                    assert any(q.get("name") == ["ilike.austin"] and q.get("stateCode") == ["eq.TX"]
                               and q.get("countryCode") == ["eq.US"] for q in queries)
                    assert any(q.get("featureCode") == ["eq.ADM1"] for q in queries)
                    assert (sentinel / "filtered_posts.csv").read_text() == "preserve existing data\n"
                    assert len(list(sentinel.iterdir())) == 1
                    print("PASS: real model → real Supabase SDK/local HTTP response → CSV → all four Dash callbacks.")
                    database_unavailable.set()
                    assert requests.get(base + "/health", timeout=10).status_code == 503
                    database_unavailable.clear()
                    assert requests.get(base + "/health", timeout=10).status_code == 200
                    print("PASS: database outage makes public readiness fail; recovery restores it.")
                    database_slow.set()
                    started = time.monotonic()
                    assert requests.get(base + "/health", timeout=10).status_code == 503
                    elapsed = time.monotonic() - started
                    assert 2 <= elapsed < 4.5, f"Database timeout did not release the worker promptly: {elapsed:.1f}s"
                    database_slow.clear()
                    assert requests.get(base + "/health", timeout=10).status_code == 200
                    print("PASS: stalled database reads release the model worker in about three seconds; recovery succeeds.")
                    model = next(child for child in descendants if any(
                        arg.endswith("/model_server.py") for arg in child.cmdline()))
                    model.send_signal(signal.SIGTERM)
                    assert process.wait(timeout=30) == 1
                    _, alive = psutil.wait_procs(descendants, timeout=10)
                    assert not alive, "Supervisor left child processes running"
                    print("PASS: model failure stops the dashboard and exits nonzero; existing data is preserved.")
                except BaseException:
                    log.flush()
                    log.seek(0)
                    print(log.read()[-12000:], file=sys.stderr)
                    raise
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=45)
                    for child in descendants:
                        if child.is_running():
                            child.kill()
                    database.shutdown()
                    thread.join()


if __name__ == "__main__":
    main()
