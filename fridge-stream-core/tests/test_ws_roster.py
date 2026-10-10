"""The credits roster only goes to clients that ask for it (/ws?credits=1), throttled."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.server import ConnectionManager  # noqa: E402


class FakeWs:
    def __init__(self, credits: bool = False):
        self.query_params = {"credits": "1"} if credits else {}
        self.sent: list[dict] = []

    async def accept(self):
        pass

    async def send_text(self, text: str):
        self.sent.append(json.loads(text))

    def types(self) -> list[str]:
        return [m.get("type") for m in self.sent]


class RosterTests(unittest.TestCase):
    def test_roster_only_to_credits_clients(self):
        async def go():
            m = ConnectionManager()
            chat, game, credits = FakeWs(), FakeWs(), FakeWs(credits=True)
            for ws in (chat, game, credits):
                await m.connect(ws)
            await m.broadcast({"type": "chat", "data": {}})
            await m.broadcast({"type": "credits_roster", "data": {"chatters": []}})
            await m.flush()             # (each client's own task sends; wait for them)
            return chat, game, credits

        chat, game, credits = asyncio.run(go())
        self.assertEqual(chat.types(), ["chat"])
        self.assertEqual(game.types(), ["chat"])
        self.assertEqual(credits.types(), ["chat", "credits_roster"])

    def test_push_roster_is_coalesced_and_throttled(self):
        built = []

        def snapshot():
            built.append(1)
            return {"count": len(built)}

        async def go():
            m = ConnectionManager()
            m.ROSTER_MIN_GAP_SEC = 0.2
            credits = FakeWs(credits=True)
            await m.connect(credits)
            for _ in range(50):          # 50 new chatters in a burst
                m.push_roster(snapshot)
            await asyncio.sleep(0.05)
            first = len(credits.sent)
            for _ in range(50):
                m.push_roster(snapshot)
            await asyncio.sleep(0.05)
            mid = len(credits.sent)      # still inside the gap: nothing new yet
            await asyncio.sleep(0.3)
            return first, mid, len(credits.sent)

        first, mid, last = asyncio.run(go())
        self.assertEqual(first, 1)
        self.assertEqual(mid, 1)
        self.assertEqual(last, 2)
        self.assertEqual(len(built), 2)   # the 2 MB snapshot is built per send, not per chatter

    def test_no_snapshot_without_credits_clients(self):
        built = []

        async def go():
            m = ConnectionManager()
            await m.connect(FakeWs())
            m.push_roster(lambda: built.append(1) or {})
            await asyncio.sleep(0.05)

        asyncio.run(go())
        self.assertEqual(built, [])


class EndToEndTests(unittest.TestCase):
    def test_connect_snapshot_only_with_credits_param(self):
        from fastapi.testclient import TestClient

        from api.server import CoreState, create_app
        from core.credits import CreditsEngine

        state = CoreState()
        state.config = {}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state.credits = CreditsEngine({"credits": {"enabled": True}}, Path(tmp.name))
        app = create_app(state)

        def first_types(client, url, n=8):
            out = []
            with client.websocket_connect(url, headers={"origin": "http://127.0.0.1:3850", "host": "127.0.0.1:3850"}) as ws:
                ws.send_text("ping")
                while True:
                    t = ws.receive_json().get("type")
                    out.append(t)
                    if t == "pong" or len(out) >= n:
                        return out

        with TestClient(app, base_url="http://127.0.0.1:3850") as client:
            plain = first_types(client, "/ws")
            credits = first_types(client, "/ws?credits=1")
        self.assertNotIn("credits_roster", plain)
        self.assertIn("credits_theme", plain)
        self.assertIn("credits_roster", credits)


if __name__ == "__main__":
    unittest.main()
