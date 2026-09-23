"""Continuous Bluesky collection; HTTP consumers drain an acknowledged disk queue."""
import asyncio
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import signal
import threading
import time

from atproto import AsyncFirehoseSubscribeReposClient, CAR, parse_subscribe_repos_message
from flask import Flask, jsonify, request

from ingest_queue import IngestQueue, QueueFull
from post_context import record_metadata

ROOT = Path(__file__).resolve().parents[3]


class CollectionPaused(Exception):
    """Stop receiving at the committed cursor while HTTP delivery stays available."""


def event_timestamp(value):
    """Use the relay's commit time, not a user's editable post publication time."""
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed > datetime.now(timezone.utc):
            return None
        return parsed.timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def commit_posts(commit):
    operations = [op for op in commit.ops
                  if op.action == 'create' and op.path.startswith('app.bsky.feed.post/')]
    if not operations:
        return []
    car = CAR.from_bytes(commit.blocks)
    posts = []
    for op in operations:
        record = car.blocks.get(op.cid)
        if not isinstance(record, dict) or record.get('$type') != 'app.bsky.feed.post':
            raise ValueError('A post operation is missing its matching CAR record')
        posts.append({'text': record.get('text', ''), 'created_at': record.get('createdAt', ''),
                      'author': commit.repo, 'uri': f'at://{commit.repo}/{op.path}',
                      **record_metadata(record)})
    return posts


class CheckpointClient(AsyncFirehoseSubscribeReposClient):
    """Prevent the SDK swallowing callback/decoding failures and skipping a checkpoint."""
    def __init__(self, collector):
        super().__init__(recv_timeout=30)
        self.collector = collector

    async def _before_connect(self):
        if self.collector.pause_requested():
            raise CollectionPaused()
        cursor = self.collector.queue.cursor
        self.update_params({'cursor': cursor} if cursor is not None else {})
        self.collector.connections += 1
        self.collector.state = 'connecting'

    async def _process_frame(self, frame):
        await self.collector.handle_message(frame)

    def _handle_frame_decoding_error(self, exception):
        raise exception


class ContinuousCollector:
    def __init__(self, queue, client_factory=CheckpointClient, pause_file=None):
        self.queue = queue
        self.client_factory = client_factory
        self.state = 'starting'
        self.last_event = None
        self.connections = 0
        self.error = None
        self.stopping = threading.Event()
        self.thread = None
        self.loop = None
        self.client = None
        self.pause_file = Path(pause_file) if pause_file is not None else None

    def pause_requested(self):
        return self.pause_file is not None and self.pause_file.is_file()

    async def handle_message(self, frame):
        if self.pause_requested():
            raise CollectionPaused()
        body = getattr(frame, 'body', {})
        if isinstance(body, dict) and body.get('error'):
            raise RuntimeError('The stream rejected this connection/cursor')
        event = parse_subscribe_repos_message(frame)
        if getattr(event, 'name', None) == 'OutdatedCursor':
            self.queue.record_gap('The saved cursor exceeded the provider replay window.')
        seq = getattr(event, 'seq', None)
        if isinstance(seq, int):
            too_big = getattr(event, 'too_big', False)
            posts = commit_posts(event) if hasattr(event, 'ops') and not too_big else []
            gap = 'A repository commit was too large to include its post records.' if too_big else None
            self.queue.append(seq, posts, gap, source_time=event_timestamp(getattr(event, 'time', None)))
            if self.client:
                self.client.update_params({'cursor': self.queue.cursor})
        self.last_event = time.time()
        self.state = 'connected'
        self.error = None

    async def run(self):
        self.loop = asyncio.get_running_loop()
        delay = 1
        while not self.stopping.is_set():
            if self.pause_requested():
                self.state = 'paused'
                self.error = None
                await asyncio.sleep(.25)
                continue
            started = time.monotonic()
            self.client = self.client_factory(self)
            try:
                await self.client.start(self.handle_message)
                if not self.stopping.is_set():
                    self.state = 'reconnecting'
            except Exception as exc:
                # SDK versions may wrap a callback exception before returning it.
                cause = exc
                while cause.__cause__ is not None:
                    cause = cause.__cause__
                if isinstance(cause, CollectionPaused):
                    self.state = 'paused'
                    self.error = None
                elif isinstance(cause, QueueFull):
                    self.state = 'backpressure'
                    self.error = 'Queue full; waiting for processing before resuming from the saved position.'
                else:
                    self.state = 'reconnecting'
                    self.error = 'Stream interrupted; retrying from the saved position.'
            finally:
                await self.client.stop()
            if time.monotonic() - started > 30:
                delay = 1
            for _ in range(delay * 10):
                if self.stopping.is_set():
                    break
                await asyncio.sleep(.1)
            delay = min(delay * 2, 30)
        self.state = 'stopped'

    def start(self):
        self.thread = threading.Thread(target=lambda: asyncio.run(self.run()), name='bluesky-collector', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.loop and self.client and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.client.stop(), self.loop)
        if self.thread:
            self.thread.join(timeout=10)

    def status(self):
        age = round(time.time() - self.last_event, 1) if self.last_event else None
        state = self.state
        if state == 'connected' and (age is None or age > 45):
            state = 'stalled'
        return {**self.queue.status(), 'state': state, 'connections': self.connections,
                'last_event_age_seconds': age, 'error': self.error}


def create_app(queue, collector):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 4096

    @app.get('/scrape')
    def scrape():
        try:
            limit = int(request.args.get('limit', 20))
            if not 1 <= limit <= 100:
                raise ValueError
        except ValueError:
            return jsonify(error='limit must be between 1 and 100'), 400
        return jsonify(**queue.take(limit), collector=collector.status())

    @app.post('/ack')
    def acknowledge():
        data = request.get_json(silent=True)
        receipt = data.get('receipt') if isinstance(data, dict) else None
        if not isinstance(receipt, str) or len(receipt) != 32:
            return jsonify(error='A batch receipt is required'), 400
        if not queue.acknowledge(receipt):
            return jsonify(error='Unknown batch receipt'), 409
        return jsonify(status='acknowledged')

    @app.get('/health')
    def health():
        status = collector.status()
        healthy = status['state'] == 'connected'
        return jsonify(status='healthy' if healthy else 'unavailable', collector=status), 200 if healthy else 503

    @app.get('/status')
    def status():
        return jsonify(collector.status())

    return app


if __name__ == '__main__':
    directory = Path(os.environ.get('CRISIS_INGEST_DIR', ROOT / '.demo-live/ingest'))
    directory.mkdir(parents=True, exist_ok=True)
    owner = (directory / 'collector.lock').open('a')
    fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
    queue = IngestQueue(directory / 'queue.sqlite3')
    collector = ContinuousCollector(queue, pause_file=directory / 'collection.paused')
    collector.start()

    def shutdown(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    try:
        create_app(queue, collector).run(host='127.0.0.1', port=int(os.environ.get('SCRAPER_PORT', '5001')))
    finally:
        collector.stop()
        queue.close()
        owner.close()
