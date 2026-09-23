#!/usr/bin/env python3
"""Run the existing model, processor, and dashboard together on one host."""

import argparse
import csv
import json
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from dotenv import load_dotenv
import requests

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "proj-dev/app/live_demo"


class ShutdownRequested(Exception):
    pass


def check_children(children):
    for name, process in children:
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited with status {process.returncode}; stopping the pipeline.")


def check_ports(env, mode):
    ports = [int(env.get('MODEL_PORT', '5000')), int(env.get('PORT', '8051'))]
    if mode == 'live':
        ports.append(int(env.get('SCRAPER_PORT', '5001')))
    if len(set(ports)) != len(ports) or not all(1 <= port <= 65535 for port in ports):
        raise ValueError('Model, collector, and dashboard need distinct valid ports.')
    for port in ports:
        # macOS may allow a wildcard bind alongside a specific-interface listener.
        with socket.socket() as connection:
            connection.settimeout(.25)
            if connection.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} is already in use. Stop the previous app before starting another.')
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('0.0.0.0', port))
                probe.listen(1)
            except OSError as exc:
                raise RuntimeError(f'Port {port} is already in use. Stop the previous app before starting another.') from exc


def wait_ready(url, children, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        check_children(children)
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200 and response.json().get("status") == "healthy":
                return
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("Backend did not become ready. Check model loading, Supabase credentials, and gazetteer columns/data.")


def stop_children(children):
    # Each child has its own process group, including Gunicorn's worker.
    for _, process in reversed(children):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _, process in reversed(children):
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def verify_startup_data(directory):
    with (Path(directory) / "filtered_posts.csv").open(newline="") as source:
        posts = list(csv.DictReader(source))
    with (Path(directory) / "crisis_counts.csv").open(newline="") as source:
        counts = list(csv.DictReader(source))
    if not any(post["city"] == "Austin" and post["state"] == "Texas" for post in posts) or not counts or not all(
        count["state"] == "Texas" and count["disasters"] == "Flood" for count in counts
    ):
        raise RuntimeError("Startup post did not resolve to Flood in Austin, Texas. Check gazetteer data/ambiguity.")


def restore_run(source, destination):
    """Copy an explicit saved run into this launcher's disposable data directory."""
    source, destination = Path(source), Path(destination)
    required = {
        'filtered_posts.csv': {'text', 'country', 'state', 'city', 'disasters'},
        'crisis_counts.csv': {'country', 'state', 'disasters', 'count'},
    }
    for name, columns in required.items():
        with (source / name).open(newline='') as stream:
            reader = csv.DictReader(stream)
            if not columns.issubset(reader.fieldnames or []):
                raise ValueError(f'Cannot resume: {name} has missing columns.')
    names = list(required)
    status = source / 'pipeline_status.json'
    if status.is_file():
        if not isinstance(json.loads(status.read_text()), dict):
            raise ValueError('Cannot resume: invalid pipeline status.')
        names.append(status.name)
    for name in names:
        shutil.copy2(source / name, destination / name)


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("demo", "live"), default=os.environ.get("CRISIS_PIPELINE_MODE", "demo"))
    parser.add_argument('--resume-from', type=Path, help='Copy CSVs and counters from an archived run; preserve the source.')
    args = parser.parse_args()
    if args.mode not in ("demo", "live"):
        parser.error("CRISIS_PIPELINE_MODE must be demo or live.")
    missing = [name for name in ("SUPABASE_URL", "SUPABASE_KEY") if not os.environ.get(name)]
    if missing:
        parser.error("Set " + ", ".join(missing) + " in the server environment; see docs/BACKEND.md.")

    env = dict(os.environ)
    env.pop("CRISIS_DATA_DIR", None)
    env["MODEL_SERVER_URL"] = f"http://127.0.0.1:{env.get('MODEL_PORT', '5000')}"
    env["SCRAPER_SERVER_URL"] = f"http://127.0.0.1:{env.get('SCRAPER_PORT', '5001')}"
    env["MODEL_THREADS"] = "1"
    env["CRISIS_PIPELINE_MODE"] = args.mode
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    children = []

    def start(name, *command):
        process = subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True)
        children.append((name, process))
        return process

    def request_shutdown(_signum, _frame):
        raise ShutdownRequested()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, request_shutdown)

    with TemporaryDirectory(prefix="crisis-pipeline-") as temporary:
        try:
            check_ports(env, args.mode)
            if args.resume_from:
                restore_run(args.resume_from, temporary)
            start("Model service", sys.executable, str(APP / "model_server.py"))
            wait_ready(env["MODEL_SERVER_URL"] + "/ready", children)
            if args.resume_from:
                print(f'Dashboard data saved to {temporary}', flush=True)
                print('Resumed saved reports and counters; no duplicate startup example added.', flush=True)
            else:
                print("Real NLP and Supabase are ready. Processing the synthetic startup post.", flush=True)
                seed = start("Startup post", sys.executable, str(APP / "process_test_tweet.py"), "--output-dir", temporary)
                seed.wait(timeout=60)
                if seed.returncode:
                    raise RuntimeError("Real model processing did not produce usable startup data; see service logs.")
                children.remove(("Startup post", seed))
                verify_startup_data(temporary)
            env["CRISIS_DATA_DIR"] = temporary

            if args.mode == "live":
                start("Firehose service", sys.executable, str(APP / "firehose_scraper_server.py"))
                wait_ready(env["SCRAPER_SERVER_URL"] + "/health", children, timeout=30)
                start("Batch processor", sys.executable, str(APP / "entry.py"))

            start("Dashboard", sys.executable, "-m", "gunicorn", "--chdir", str(APP),
                  "dash_client:server", "--bind", f"0.0.0.0:{env.get('PORT', '8051')}",
                  "--workers", "1", "--threads", "2", "--graceful-timeout", "10",
                  "--access-logfile", "-", "--error-logfile", "-")
            print(f"Pipeline running in {args.mode} mode. Report CSVs are scoped to this server run.", flush=True)
            while True:
                check_children(children)
                time.sleep(1)
        except ShutdownRequested:
            return 0
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"Pipeline startup/runtime failure: {exc}", file=sys.stderr, flush=True)
            return 1
        finally:
            # Ignore repeated shutdown signals while the children are draining.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            stop_children(children)


if __name__ == "__main__":
    sys.exit(main())
