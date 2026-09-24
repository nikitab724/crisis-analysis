"""Read-only, synthetic interview replay; never invokes live analysis or storage."""

import json
from pathlib import Path

import pandas as pd


DATASET_PATH = Path(__file__).parent / "fixtures" / "interview_feed.json"
POST_COLUMNS = ["text", "city", "state", "country", "disasters", "latitude", "longitude"]


def load_samples():
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    posts = data["posts"]
    if data["version"] != 1 or not posts or len({post["id"] for post in posts}) != len(posts):
        raise ValueError("Invalid interview dataset")
    for post in posts:
        if post["outcome"] not in ("mapped", "skipped", "unmapped") or not post["text"]:
            raise ValueError("Invalid sample outcome")
        if post["outcome"] == "mapped":
            if not all(post.get(key) for key in ("city", "state", "disaster")):
                raise ValueError("Mapped samples require a location and category")
            if not (-90 <= post["latitude"] <= 90 and -180 <= post["longitude"] <= 180):
                raise ValueError("Invalid sample coordinates")
    return posts


def visible_samples(samples, state=None):
    """Clamp the browser's cursor; initial page shows the complete demonstration."""
    cursor = state.get("cursor") if isinstance(state, dict) else len(samples)
    if type(cursor) is not int:
        cursor = len(samples)
    return samples[:max(0, min(cursor, len(samples)))]


def mapped_posts(samples, state=None):
    return pd.DataFrame([
        {"text": post["text"], "city": post["city"], "state": post["state"],
         "country": "US", "disasters": [post["disaster"]],
         "latitude": post["latitude"], "longitude": post["longitude"]}
        for post in visible_samples(samples, state) if post["outcome"] == "mapped"
    ], columns=POST_COLUMNS)
