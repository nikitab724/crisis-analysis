"""Small, local activity snapshots for the CSV-based pipeline."""

from datetime import datetime, timezone
import json
from pathlib import Path


def read_status(directory):
    try:
        value = json.loads((Path(directory) / "pipeline_status.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(directory, **updates):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    status = read_status(directory)
    status.update(updates)
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary = directory / "pipeline_status.json.tmp"
    temporary.write_text(json.dumps(status) + "\n")
    temporary.replace(directory / "pipeline_status.json")


def save_csv(frame, path):
    """Publish a complete CSV so refreshes cannot read a partial write."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)
