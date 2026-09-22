"""Collector regressions; install requirements-live.txt to run these checks."""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "proj-dev/app/live_demo"))
try:
    import firehose_scraper_server as firehose
except ModuleNotFoundError:
    firehose = None


def tearDownModule():
    if firehose is not None:
        firehose.loop.close()


@unittest.skipIf(firehose is None, "Requires live collector dependencies")
class FirehoseTests(unittest.TestCase):
    def test_commit_uses_the_record_for_the_operation_cid(self):
        records = {
            "first": {"$type": "app.bsky.feed.post", "text": "Unrelated first record"},
            "target": {"$type": "app.bsky.feed.post", "text": "Correct second record"},
        }
        commit = SimpleNamespace(blocks=b"example", repo="did:plc:sample")
        op = SimpleNamespace(cid="target", path="app.bsky.feed.post/second")
        resolver = SimpleNamespace(did=SimpleNamespace(resolve=AsyncMock(
            return_value=SimpleNamespace(also_known_as=["at://sample.bsky.social"]))))
        with patch.object(firehose.CAR, "from_bytes", return_value=SimpleNamespace(blocks=records)):
            post = asyncio.run(firehose.process_post(commit, op, resolver))
        self.assertEqual(post["text"], "Correct second record")
        self.assertTrue(post["uri"].endswith("/second"))

    def test_slow_batch_returns_partial_posts_and_closes_connection(self):
        client = SimpleNamespace(stop=AsyncMock())
        async def partial(_client, _resolver, _limit, posts):
            posts.append({"text": "Already received"})
            raise asyncio.TimeoutError
        with patch.object(firehose, "AsyncFirehoseSubscribeReposClient", return_value=client):
            with patch.object(firehose, "listen_firehose", side_effect=partial):
                api = firehose.FirehoseAPI()
                posts = asyncio.run(api.fetch_posts(100))
        self.assertEqual(posts, [{"text": "Already received"}])
        client.stop.assert_awaited_once()

    def test_oversized_batch_is_rejected_without_opening_a_feed(self):
        with patch.object(firehose.scraper, "fetch_posts", new=Mock()) as fetch:
            self.assertEqual(firehose.app.test_client().get("/scrape?limit=101").status_code, 400)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
