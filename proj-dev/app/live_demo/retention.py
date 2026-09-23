"""A rolling publication-time window for the live report feed."""
import os
from pathlib import Path

import pandas as pd

RETENTION_HOURS = 24


def live_retention_enabled(directory):
    return os.environ.get('CRISIS_PIPELINE_MODE') == 'live' and not (Path(directory) / 'fixture-demo.json').is_file()


def recent_posts(posts, now=None):
    """Expire at 24 hours; undated, invalid, or future-dated posts are not current."""
    if posts.empty or 'created_at' not in posts:
        return posts.iloc[:0].copy()
    current = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    current = current.tz_localize('UTC') if current.tzinfo is None else current.tz_convert('UTC')
    posted = pd.to_datetime(posts['created_at'], format='mixed', errors='coerce', utc=True)
    valid = posted.gt(current - pd.Timedelta(hours=RETENTION_HOURS)) & posted.le(current)
    return posts.loc[valid].copy()
