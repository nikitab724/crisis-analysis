#!/usr/bin/env python3
"""Locally pause/resume incoming posts without stopping queued-post delivery."""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def set_collection_state(directory, action):
    directory = Path(directory).expanduser().resolve()
    if not (directory / 'queue.sqlite3').is_file():
        raise ValueError('No existing collection queue in that directory.')
    marker = directory / 'collection.paused'
    if action == 'pause':
        marker.touch(exist_ok=True)
    elif action == 'resume':
        marker.unlink(missing_ok=True)
    elif action != 'status':
        raise ValueError('Expected pause, resume, or status.')
    return marker.is_file()


def main():
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('pause', 'resume', 'status'))
    parser.add_argument('--ingest-dir', type=Path,
                        default=Path(os.environ.get('CRISIS_INGEST_DIR', ROOT / '.demo-live/ingest')))
    args = parser.parse_args()
    try:
        paused = set_collection_state(args.ingest_dir, args.action)
    except ValueError as exc:
        parser.error(str(exc))
    print('Collection pause requested; saved posts remain available for processing.' if paused else
          'Collection enabled; reconnects use the saved stream position.')


if __name__ == '__main__':
    main()
