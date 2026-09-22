#!/usr/bin/env python3
"""Inject one synthetic post through entry.py without touching live CSVs."""

import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch

import pandas as pd

import entry

DEFAULT_TEXT = "Flood in Austin Texas."
FIXTURE_FILE = Path(__file__).parent / "fixtures/flood_austin.json"
OUTPUT_FILES = ("filtered_posts.csv", "crisis_counts.csv")


def create_mock_post(text):
    """Use a fixed ID and timestamp so repeated demo runs are comparable."""
    return [{
        "author": "synthetic-demo",
        "created_at": "2025-04-21T12:00:00Z",
        "post_id": "demo-flood-austin",
        "text": text,
        "uri": "at://did:plc:demo/app.bsky.feed.post/demo-flood-austin",
    }]


@contextmanager
def fixture_model_server():
    """Replay one predefined response over the pipeline's normal HTTP boundary."""
    fixture = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path != "/extract_entities" or request != {"text": fixture["text"]}:
                self.send_error(400, "Fixture supports only the bundled demo post")
                return
            payload = json.dumps(fixture["response"]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.object(entry, "MODEL_SERVER_URL", f"http://127.0.0.1:{server.server_port}"):
                yield
        finally:
            server.shutdown()
            worker.join()


def process_test_tweet(text=DEFAULT_TEXT, *, fixture=False, output_dir=None):
    """Run real processing by default; fixture mode explicitly replaces model HTTP.

    A temporary directory isolates each run from existing data. Only validated
    results are exported, and the original scraper function is always restored.
    """
    if not text.strip():
        raise ValueError("Post text must not be empty.")
    if fixture and text != DEFAULT_TEXT:
        raise ValueError("Fixture mode only supports the bundled Flood/Austin Texas post.")

    with TemporaryDirectory(prefix="crisis-demo-") as temporary:
        with patch.object(entry, "get_scraped_posts", return_value=create_mock_post(text)):
            if fixture:
                print("FIXTURE DEMO: predefined model response; no live NLP or Supabase lookup.")
                with fixture_model_server(), patch.object(entry, "get_relevance_client", return_value=None):
                    entry.main(post_limit=1, output_dir=temporary)
            else:
                print("LIVE MODEL: synthetic post sent to the configured model service.")
                entry.main(post_limit=1, output_dir=temporary)

        paths = [Path(temporary) / name for name in OUTPUT_FILES]
        if not all(path.exists() for path in paths):
            raise RuntimeError(
                "Demo failed: no complete crisis output. Check model health, "
                "DISASTER/location detection, and the Supabase gazetteer."
            )
        posts, counts = (pd.read_csv(path) for path in paths)
        if posts.empty or counts.empty or not posts["text"].eq(text).all():
            raise RuntimeError("Demo failed: expected the injected post and nonempty crisis counts.")
        if fixture and not (
            len(posts) == len(counts) == 1
            and posts.iloc[0]["city"] == "Austin"
            and counts.iloc[0]["state"] == "Texas"
            and counts.iloc[0]["disasters"] == "Flood"
            and counts.iloc[0]["count"] == 1
        ):
            raise RuntimeError("Fixture output did not match the expected Flood/Austin/Texas result.")

        if output_dir is not None:
            destination = Path(output_dir).resolve()
            if destination == Path(__file__).parent.resolve() or destination == entry.DATA_DIR:
                raise ValueError("Use a separate demo directory to preserve live CSVs.")
            destination.mkdir(parents=True, exist_ok=True)
            for path in paths:
                shutil.copyfile(path, destination / path.name)
            marker = destination / "fixture-demo.json"
            if fixture:
                marker.write_text(json.dumps({"mode": "fixture", "text": text}) + "\n", encoding="utf-8")
            else:
                marker.unlink(missing_ok=True)
            print(f"Dashboard data saved to {destination}")

        print(posts[["text", "disasters", "city", "state", "sentiment"]].to_string(index=False))
        print(counts.to_string(index=False))
        print("PASS: injected post produced crisis records and aggregated counts.")
        return posts, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default=DEFAULT_TEXT, help="Synthetic post text for the live model")
    parser.add_argument("--fixture", action="store_true", help="Replay a labeled predefined model response")
    parser.add_argument("--output-dir", type=Path, help="Export validated results; replaces this directory's demo CSVs")
    args = parser.parse_args()
    try:
        process_test_tweet(args.text, fixture=args.fixture, output_dir=args.output_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Demo failed: {exc}\n")


if __name__ == "__main__":
    main()
