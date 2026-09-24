"""Read a frozen snapshot of public posts and their saved pipeline results."""

import json
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from us_scope import is_us_location


DATASET_PATH = Path(__file__).parent / "fixtures" / "interview_feed.json"
POST_COLUMNS = ["text", "uri", "city", "state", "country", "disasters", "latitude", "longitude"]


def source_url(uri):
    """Link only to an original Bluesky post, never to a supplied external URL."""
    parts = uri[5:].split("/") if isinstance(uri, str) and uri.startswith("at://") else []
    if len(parts) != 3 or parts[1] != "app.bsky.feed.post" or not parts[0] or not parts[2]:
        raise ValueError("A saved post requires its original Bluesky URI")
    return f"https://bsky.app/profile/{quote(parts[0], safe=':')}/post/{quote(parts[2], safe='')}"


def load_samples():
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    posts = data["posts"]
    if (data["version"] != 2 or data["source"] != "processed_bluesky" or not posts
            or len({post["uri"] for post in posts}) != len(posts)):
        raise ValueError("Invalid saved-post dataset")
    for post in posts:
        source_url(post["uri"])
        posted = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
        if not posted.tzinfo or not post["text"].strip() or not post["records"]:
            raise ValueError("Saved posts require text, a date, and processed records")
        for record in post["records"]:
            labels = record["disasters"]
            if not is_us_location(record) or not isinstance(labels, list) or not labels:
                raise ValueError("Saved records require a US location and categories")
            if not all(isinstance(label, str) and label.strip() for label in labels):
                raise ValueError("Invalid saved categories")
            for key, bound in (("latitude", 90), ("longitude", 180)):
                value = record[key]
                if value is not None and (not math.isfinite(value) or not -bound <= value <= bound):
                    raise ValueError("Invalid saved coordinates")
    return posts


def mapped_posts(samples):
    """Keep all saved locations, while showing each source post once in the feed."""
    return pd.DataFrame([
        {"text": post["text"], "uri": post["uri"], **record}
        for post in samples for record in post["records"]
    ], columns=POST_COLUMNS)
