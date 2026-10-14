"""Kick's Pusher chat key: asked from Kick, pinned by hand, and a refused key spotted.
Run from fridge-stream-core:

    python -m unittest tests.test_kick_pusher_key -v
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from websockets.exceptions import ConnectionClosedError  # noqa: E402
from websockets.frames import Close  # noqa: E402

from adapters import kick  # noqa: E402
from adapters.kick import (  # noqa: E402
    KickAdapter, is_bad_key_close, pusher_credentials_from, pusher_url,
)
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402

# Kick's answer to POST web.kick.com/api/v1/realtime/connection (October 2026)
REALTIME_ANSWER = {
    "data": {
        "connections": [
            {"provider": "pusher", "credentials": {"app_key": "34bf7a0ff419a2a775b9", "cluster": "us2"}},
        ]
    }
}


def adapter(**kick_cfg) -> KickAdapter:
    cfg = {"kick": {"channel_slug": "sensoka-flavr", **kick_cfg}}
    return KickAdapter(cfg, EventBus(), MetricsAggregator(cfg))


class PusherKeyTest(unittest.TestCase):
    def test_reads_kick_realtime_answer(self):
        self.assertEqual(pusher_credentials_from(REALTIME_ANSWER), ("34bf7a0ff419a2a775b9", "us2"))

    def test_skips_other_providers_and_junk(self):
        other = {"data": {"connections": [
            {"provider": "centrifugo", "credentials": {"url": "wss://x"}},
            {"provider": "pusher", "credentials": {"app_key": "abc123", "cluster": "eu"}},
        ]}}
        self.assertEqual(pusher_credentials_from(other), ("abc123", "eu"))
        for junk in (None, [], {}, {"data": {"connections": "x"}},
                     {"data": {"connections": [{"provider": "pusher", "credentials": {"app_key": "a/b"}}]}}):
            self.assertIsNone(pusher_credentials_from(junk))

    def test_url_uses_key_and_cluster(self):
        url = pusher_url("abc123", "eu")
        self.assertTrue(url.startswith("wss://ws-eu.pusher.com/app/abc123?protocol=7"))
        self.assertNotIn("32cbd69e4b950bf97679", kick.PUSHER_URL)

    def test_bad_key_close_spotted(self):
        bad = ConnectionClosedError(Close(4001, "App key x not in this cluster"), None)
        self.assertTrue(is_bad_key_close(bad))
        other = ConnectionClosedError(Close(1006, ""), None)
        self.assertFalse(is_bad_key_close(other))

    def test_refresh_takes_kick_answer(self):
        a = adapter()

        async def fake():
            return ("newkey123", "mt1")

        a.fetch_pusher_credentials = fake
        asyncio.run(a._refresh_pusher_key())
        self.assertEqual((a.pusher_key, a.pusher_cluster), ("newkey123", "mt1"))

    def test_refresh_failure_keeps_backup_key(self):
        a = adapter()

        async def fake():
            return None

        a.fetch_pusher_credentials = fake
        asyncio.run(a._refresh_pusher_key())
        self.assertEqual((a.pusher_key, a.pusher_cluster), (kick.PUSHER_KEY, kick.PUSHER_CLUSTER))

    def test_pinned_key_is_not_replaced(self):
        a = adapter(pusher_key="mykey", pusher_cluster="eu")

        async def fake():
            raise AssertionError("should not ask Kick when the key is pinned")

        a.fetch_pusher_credentials = fake
        asyncio.run(a._refresh_pusher_key())
        self.assertEqual((a.pusher_key, a.pusher_cluster), ("mykey", "eu"))


if __name__ == "__main__":
    unittest.main()
