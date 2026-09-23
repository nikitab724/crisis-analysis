"""Single-collector, single-consumer disk queue with atomic stream checkpoints."""
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid


class QueueFull(Exception):
    pass


class IngestQueue:
    def __init__(self, path, capacity=100_000):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.capacity = capacity
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY, uri TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL, received REAL NOT NULL, receipt TEXT);
            CREATE TABLE IF NOT EXISTS seen (uri TEXT PRIMARY KEY, processed REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS seen_processed ON seen(processed);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')

    def _get(self, key, default=None):
        row = self.db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _set(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)', (key, json.dumps(value)))

    @property
    def cursor(self):
        with self.lock:
            return self._get('cursor')

    def record_gap(self, reason):
        with self.lock, self.db:
            self._set('gap_events', self._get('gap_events', 0) + 1)
            self._set('last_gap', reason)

    def append(self, seq, posts, gap=None):
        """A checkpoint never advances beyond posts not yet committed to disk."""
        with self.lock, self.db:
            previous = self._get('cursor')
            if previous is not None and seq <= previous:
                return 0
            size = self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
            added = duplicates = 0
            for post in posts:
                uri = post['uri']
                if (self.db.execute('SELECT 1 FROM seen WHERE uri=?', (uri,)).fetchone()
                        or self.db.execute('SELECT 1 FROM posts WHERE uri=?', (uri,)).fetchone()):
                    duplicates += 1
                    continue
                if size + added >= self.capacity:
                    raise QueueFull('Pending queue is full; the cursor has not advanced.')
                self.db.execute('INSERT INTO posts(uri,payload,received) VALUES (?,?,?)',
                                (uri, json.dumps(post), time.time()))
                added += 1
            self._set('cursor', seq)
            self._set('captured', self._get('captured', 0) + added)
            self._set('duplicate_posts', self._get('duplicate_posts', 0) + duplicates)
            if gap:
                self._set('gap_events', self._get('gap_events', 0) + 1)
                self._set('last_gap', gap)
            return added

    def take(self, limit):
        """Redeliver unfinished work; only explicit acknowledgement removes it."""
        with self.lock, self.db:
            active = self.db.execute('SELECT receipt FROM posts WHERE receipt IS NOT NULL LIMIT 1').fetchone()
            if active:
                receipt = active[0]
            else:
                ids = [row[0] for row in self.db.execute('SELECT id FROM posts ORDER BY id LIMIT ?', (limit,))]
                if not ids:
                    return {'posts': [], 'receipt': None}
                receipt = uuid.uuid4().hex
                self.db.executemany('UPDATE posts SET receipt=? WHERE id=?', [(receipt, item) for item in ids])
            rows = self.db.execute('SELECT payload FROM posts WHERE receipt=? ORDER BY id', (receipt,)).fetchall()
            return {'posts': [json.loads(row[0]) for row in rows], 'receipt': receipt}

    def acknowledge(self, receipt):
        with self.lock, self.db:
            rows = self.db.execute('SELECT uri FROM posts WHERE receipt=?', (receipt,)).fetchall()
            if not rows:
                return receipt == self._get('last_ack')
            now = time.time()
            self.db.executemany('INSERT OR REPLACE INTO seen VALUES (?,?)', [(row[0], now) for row in rows])
            self.db.execute('DELETE FROM posts WHERE receipt=?', (receipt,))
            self._set('last_ack', receipt)
            total = self._get('acknowledged', 0) + len(rows)
            self._set('acknowledged', total)
            # Bound history; the durable cursor also rejects older stream events.
            if total // 1000 != (total - len(rows)) // 1000:
                self.db.execute('DELETE FROM seen WHERE processed < ?', (now - 7 * 86400,))
                self.db.execute('DELETE FROM seen WHERE uri IN '
                                '(SELECT uri FROM seen ORDER BY processed DESC LIMIT -1 OFFSET 200000)')
            return True

    def status(self):
        with self.lock:
            pending, oldest = self.db.execute('SELECT COUNT(*),MIN(received) FROM posts').fetchone()
            return {'queue_depth': pending, 'queue_capacity': self.capacity,
                    'oldest_pending_seconds': round(max(0, time.time() - oldest), 1) if oldest else 0,
                    **{key: self._get(key, 0) for key in
                       ('captured', 'acknowledged', 'duplicate_posts', 'gap_events')},
                    'cursor': self._get('cursor'), 'last_gap': self._get('last_gap')}

    def close(self):
        with self.lock:
            self.db.close()
