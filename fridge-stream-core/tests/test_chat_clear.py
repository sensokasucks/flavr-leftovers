"""Clearing Chat history: Clear history… (all / filtered / older than / keep red-flagged),
chat_log.keep_days trimming, and the CSV of what would go.

    python -m unittest tests.test_chat_clear -v
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import store as store_mod  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.store import Store  # noqa: E402

DAY = 86400


def chat(name: str, text: str, platform: Platform = Platform.TWITCH, age_days: float = 0) -> ChatEvent:
    user = ChatUser(platform=platform, id="id-" + name, username=name, display_name=name.title())
    return ChatEvent(platform=platform, user=user, message=text, timestamp=time.time() - age_days * DAY)


class StoreClearTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "core.db"
        self.store = Store(self.db, {"enabled": True, "per_message": 5, "cooldown_sec": 0}, {"enabled": True})
        for ev in (
            chat("old", "ancient line", age_days=40),
            chat("old", "older line", age_days=10),
            chat("new", "fresh line"),
            chat("kicker", "kick line", Platform.KICK, age_days=40),
            chat("troll", "buy viewers", age_days=40),
        ):
            await self.store.process_chat(ev)
        await self.store.add_red_flag(platform="twitch", platform_user_id="id-troll", username="troll",
                                      display_name="Troll", phrase="buy viewers", message="", source="phrase")

    def lines(self) -> list[str]:
        with sqlite3.connect(self.db) as conn:
            return sorted(r[0] for r in conn.execute("SELECT message FROM chat_messages"))

    async def test_everything_keeps_red_flagged_by_default(self):
        self.assertEqual(await self.store.count_chat_to_clear(), 4)
        self.assertEqual(await self.store.clear_chat(), 4)
        self.assertEqual(self.lines(), ["buy viewers"])

    async def test_everything_including_red_flagged(self):
        self.assertEqual(await self.store.clear_chat(keep_flagged=False), 5)
        self.assertEqual(self.lines(), [])

    async def test_older_than(self):
        self.assertEqual(await self.store.clear_chat(30), 2)   # ancient + kick; troll kept
        self.assertEqual(self.lines(), ["buy viewers", "fresh line", "older line"])

    async def test_filtered(self):
        self.assertEqual(await self.store.clear_chat(platform="kick"), 1)
        self.assertEqual(await self.store.clear_chat(q="OLDER"), 1)
        self.assertEqual(self.lines(), ["ancient line", "buy viewers", "fresh line"])
        # 🚩 only + keep red-flagged = nothing; untick keep to clear them
        self.assertEqual(await self.store.clear_chat(keep_flagged=True, flagged_only=True), 0)
        self.assertEqual(await self.store.clear_chat(keep_flagged=False, flagged_only=True), 1)
        self.assertEqual(self.lines(), ["ancient line", "fresh line"])

    async def test_points_and_people_stay(self):
        before = await self.store.stats()
        await self.store.clear_chat(keep_flagged=False)
        after = await self.store.stats()
        self.assertEqual(after["messages"], 0)
        self.assertEqual(after["users"], before["users"])
        self.assertEqual(after["total_points"], before["total_points"])
        self.assertEqual(len(self.store.list_red_flagged_sync()), 1)

    async def test_keep_days_trim(self):
        self.assertEqual(await self.store.trim_chat_log(), 0)   # 0 = keep forever
        self.store.configure_chat_log({"enabled": True, "keep_days": 7})
        self.assertEqual(await self.store.trim_chat_log(), 3)
        self.assertEqual(self.lines(), ["buy viewers", "fresh line"])
        self.store.configure_chat_log({"enabled": True, "keep_days": "nonsense"})
        self.assertEqual(self.store.log_keep_days, 0)

    async def test_csv_of_what_would_go(self):
        text = await self.store.export_chat_csv(older_than_days=30, keep_flagged=True)
        self.assertIn("ancient line", text)
        self.assertIn("kick line", text)
        self.assertNotIn("buy viewers", text)
        self.assertNotIn("fresh line", text)

    def disk_size(self) -> int:
        """The database plus its write-ahead log (WAL mode keeps new pages there first)."""
        wal = Path(str(self.db) + "-wal")
        return os.path.getsize(self.db) + (os.path.getsize(wal) if wal.exists() else 0)

    async def test_big_clear_shrinks_file_while_writer_runs(self):
        self.store.start_writer()
        for i in range(3000):
            self.store.submit_chat(chat(f"u{i % 50}", "x" * 200, age_days=20))
        await self.store.process_chat(chat("u0", "warm writer connection"))
        size = self.disk_size()
        with mock.patch.object(store_mod, "CLEAR_SHRINK_MIN", 100):
            self.assertGreaterEqual(await self.store.clear_chat(15), 3000)
        self.assertLess(self.disk_size(), size / 2)
        # the writer keeps working after the shrink
        await self.store.process_chat(chat("new", "after the clear"))
        await self.store.stop_writer()
        self.assertIn("after the clear", self.lines())


class ClearRouteTests(unittest.TestCase):
    def test_clear_endpoint(self):
        import asyncio

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.admin_routes import create_admin_router
        from api.server import CoreState

        token = "unit-test-admin-token-123456"
        disk = {"points": {"admin_token": token}, "chat_log": {"enabled": True}}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(Path(tmp.name) / "t.db", None, {"enabled": True})
        for ev in (chat("a", "one", age_days=3), chat("b", "two"), chat("c", "three", Platform.KICK)):
            asyncio.run(store.process_chat(ev))
        state = CoreState()
        state.config = json.loads(json.dumps(disk))
        state.store = store
        app = FastAPI()
        app.include_router(create_admin_router(state))
        hdr = {"X-Admin-Token": token}
        with mock.patch("api.admin_routes.load_config", lambda: json.loads(json.dumps(disk))):
            with TestClient(app) as client:
                self.assertEqual(client.post("/api/admin/chat/clear", json={}).status_code, 401)
                d = client.post("/api/admin/chat/clear", headers=hdr, json={"dry_run": True}).json()
                self.assertEqual(d["count"], 3)
                # filters only count when "filtered" is ticked
                d = client.post("/api/admin/chat/clear", headers=hdr,
                                json={"dry_run": True, "platform": "kick"}).json()
                self.assertEqual(d["count"], 3)
                d = client.post("/api/admin/chat/clear", headers=hdr,
                                json={"dry_run": True, "filtered": True, "platform": "KICK"}).json()
                self.assertEqual(d["count"], 1)
                d = client.post("/api/admin/chat/clear", headers=hdr, json={"older_than_days": 1}).json()
                self.assertEqual(d["deleted"], 1)
                self.assertEqual(len(client.get("/api/admin/chat", headers=hdr).json()), 2)
                r = client.get("/api/admin/chat/export", headers=hdr, params={"older_than_days": 1})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(client.post("/api/admin/chat/clear", headers=hdr,
                                             json={"older_than_days": -1}).status_code, 422)
                self.assertEqual(client.get("/api/admin/status", headers=hdr).json()["chat_log_keep_days"], 0)


if __name__ == "__main__":
    unittest.main()
