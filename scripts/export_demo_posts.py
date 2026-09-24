#!/usr/bin/env python3
"""Freeze existing processed Bluesky posts for the demo; no network or analysis."""

import argparse
import ast
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proj-dev/app/live_demo"))

from sample_feed import DATASET_PATH, source_url  # noqa: E402
from us_scope import is_us_location  # noqa: E402


def export_posts(source):
    """Allowlist public post fields, preserve predictions, group by original URI."""
    source = Path(source)
    posts = {}
    seen_records = set()
    excluded = 0
    with source.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                uri = row["uri"]
                source_url(uri)
                if not is_us_location(row) or not row["text"].strip():
                    raise ValueError("Not a processed public US post")
                posted = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                if not posted.tzinfo:
                    raise ValueError("Missing timezone")
                labels = ast.literal_eval(row["disasters"])
                if not isinstance(labels, list) or not labels or not all(isinstance(x, str) and x for x in labels):
                    raise ValueError("Missing saved categories")
                record = {key: row[key] for key in ("city", "state", "country")}
                record["disasters"] = labels
                for key, bound in (("latitude", 90), ("longitude", 180)):
                    value = float(row[key]) if row.get(key) else None
                    if value is not None and (not math.isfinite(value) or not -bound <= value <= bound):
                        raise ValueError("Invalid coordinates")
                    record[key] = value
            except (KeyError, ValueError, SyntaxError, TypeError):
                excluded += 1
                continue
            identity = (uri, json.dumps(record, sort_keys=True))
            if identity in seen_records:
                continue
            seen_records.add(identity)
            post = posts.setdefault(uri, {"uri": uri, "created_at": row["created_at"],
                                          "text": row["text"], "records": []})
            post["records"].append(record)
    if not posts:
        raise ValueError("No processed public US posts found; existing snapshot was not changed")
    return {
        "version": 2,
        "source": "processed_bluesky",
        "description": "Previously collected public Bluesky posts with saved pipeline classifications and locations. Historical reports, not verified incidents or current alerts. Text is preserved from the processed CSV.",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "excluded_rows": excluded,
        "posts": sorted(posts.values(), key=lambda p: (datetime.fromisoformat(p["created_at"].replace("Z", "+00:00")), p["uri"])),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Existing filtered_posts.csv")
    parser.add_argument("--output", type=Path, default=DATASET_PATH)
    args = parser.parse_args()
    snapshot = export_posts(args.input)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(snapshot['posts'])} posts and {sum(len(p['records']) for p in snapshot['posts'])} location records; excluded {snapshot['excluded_rows']} rows.")


if __name__ == "__main__":
    main()
