"""Exercise real NLP and model HTTP with a controlled Supabase query response.

This integration check does not validate a real Supabase database or Bluesky.
"""

import os
from pathlib import Path
import sys
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proj-dev/app/live_demo"))
import entry  # noqa: E402
from process_test_tweet import process_test_tweet  # noqa: E402

query = Mock()
for method in ("select", "eq", "or_", "order", "limit"):
    getattr(query, method).return_value = query
query.execute.side_effect = [
    SimpleNamespace(data=[{"name": "Austin", "featureCode": "PPL", "stateCode": "TX",
                           "countryCode": "US", "latitude": 30.2672, "longitude": -97.7431}]),
    SimpleNamespace(data=[{"name": "Texas", "featureCode": "ADM1", "stateCode": "TX",
                           "countryCode": "US", "latitude": 31.4757, "longitude": -99.3312}]),
]
client = Mock()
client.table.return_value = query
with patch.dict(os.environ, {"SUPABASE_URL": "https://fixture.invalid", "SUPABASE_KEY": "fixture-only"}):
    with patch("supabase.create_client", return_value=client):
        import model_server

model_server.initialize_globals()
assert model_server.nlp is not None
with make_server("127.0.0.1", 0, model_server.app) as server:
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        assert requests.get(f"{base}/health", timeout=10).json()["status"] == "healthy"
        with patch.object(entry, "MODEL_SERVER_URL", base):
            posts, counts = process_test_tweet()
        assert set(posts["state"]) == {"Texas"}
        assert "Austin" in set(posts["city"].dropna())
        assert counts.iloc[0]["disasters"] == "Flood"
        # Preserve current record counting: Austin + Texas produce two location rows.
        assert counts.iloc[0]["count"] == len(posts) == 2
        assert query.execute.call_count == 2
        with patch.object(model_server, "nlp", None):
            response = requests.post(f"{base}/extract_entities", json={"text": "Flood"}, timeout=10)
            assert response.status_code == 503
    finally:
        server.shutdown()
        worker.join()
print("PASS: real NLP → model HTTP → gazetteer response fixture → CSV aggregation; missing model returns 503.")
