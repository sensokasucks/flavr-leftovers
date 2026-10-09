"""A busy chat: batched database writes, slow overlay clients, red flags, picture-link files.

    python -m unittest tests.test_busy_chat -v
"""

from __future__ import annotations

import asyncio
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

from adapters import avatar_link_file  # noqa: E402
from api.server import ConnectionManager  # noqa: E402
from core import store as store_mod  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.red_flags import RedFlags  # noqa: E402
from core.store import Store  # noqa: E402


def chat(name: str, text: str = "hi", platform: Platform = Platform.TWITCH) -> ChatEvent:
    user = ChatUser(platform=platform, id="id-" + name, username=name, display_name=name.title())
    return ChatEvent(platform=platform, user=user, message=text)


class BatchedWriterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "core.db"
        self.store = Store(self.db, {"enabled": True, "per_message": 1, "cooldown_sec": 0},
                           {"enabled": True})

    def count(self, sql: str, *args) -> int:
        with sqlite3.connect(self.db) as conn:
            return conn.execute(sql, args).fetchone()[0]

    async def test_many_lines_few_transactions(self):
        calls = []
        real = self.store._write_batch_sync

        def counting(batch, keep_conn=False):
            calls.append(len(batch))
            return real(batch, keep_conn)

        self.store._write_batch_sync = counting
        self.store.start_writer()
        for i in range(1200):
            self.store.submit_chat(chat(f"user{i % 30}", f"line {i}"))
        await self.store.stop_writer()
        self.assertEqual(sum(calls), 1200)
        self.assertLess(len(calls), 10)           # 1200 lines in a handful of transactions
        self.assertEqual(self.count("SELECT COUNT(*) FROM chat_messages"), 1200)
        self.assertEqual(self.count("SELECT COUNT(*) FROM users"), 30)
        self.assertEqual(self.count("SELECT SUM(points) FROM users"), 1200)

    async def test_process_chat_waits_for_its_result(self):
        self.store.start_writer()
        try:
            res = await self.store.process_chat(chat("ann"))
            self.assertEqual(res["awarded"], 1)
            self.assertEqual(res["balance"], 1)
            self.assertTrue(res["logged"])
            again = await self.store.process_chat(chat("ann"))
            self.assertEqual(again["user_id"], res["user_id"])
            self.assertEqual(again["balance"], 2)
        finally:
            await self.store.stop_writer()

    async def test_without_writer_lines_are_written_at_once(self):
        self.store.submit_chat(chat("bob"))
        self.assertEqual(self.count("SELECT COUNT(*) FROM chat_messages"), 1)

    async def test_flagged_line_logged_without_points(self):
        self.store.start_writer()
        self.store.submit_chat(chat("eve"), award=False, flagged=True)
        await self.store.stop_writer()
        self.assertEqual(self.count("SELECT COUNT(*) FROM chat_messages"), 1)
        self.assertEqual(self.count("SELECT SUM(points) FROM users"), 0)

    async def test_merge_while_chat_is_being_written(self):
        self.store.start_writer()
        a = await self.store.process_chat(chat("kickann", platform=Platform.KICK))
        b = await self.store.process_chat(chat("twitchann"))
        for _ in range(50):
            self.store.submit_chat(chat("kickann", platform=Platform.KICK))
            self.store.submit_chat(chat("twitchann"))
        merged = await self.store.merge_users(a["user_id"], b["user_id"])
        self.assertTrue(merged["ok"])
        for _ in range(10):
            self.store.submit_chat(chat("twitchann"))
        await self.store.stop_writer()
        # every line saved, all of them on the kept user, and the cache follows the merge
        self.assertEqual(self.count("SELECT COUNT(*) FROM chat_messages"), 112)
        self.assertEqual(self.count("SELECT COUNT(*) FROM users"), 1)
        self.assertEqual(self.count("SELECT COUNT(*) FROM chat_messages WHERE user_id=?", a["user_id"]), 112)
        self.assertEqual(self.count("SELECT points FROM users WHERE id=?", a["user_id"]), 112)

    async def test_full_queue_drops_database_lines_only(self):
        with mock.patch.object(store_mod, "CHAT_QUEUE_MAX", 5):
            self.store.start_writer()
        for i in range(20):
            self.store.submit_chat(chat(f"u{i}"))   # no await: the writer has not run yet
        self.assertEqual(self.store._dropped, 15)
        await self.store.stop_writer()
        self.assertEqual(self.count("SELECT COUNT(*) FROM chat_messages"), 5)


class FakeWS:
    def __init__(self, stuck: bool = False):
        self.stuck = stuck
        self.got: list[str] = []
        self.closed = None
        self.query_params = {}

    async def accept(self):
        pass

    async def send_text(self, text: str):
        if self.stuck:
            await asyncio.Event().wait()     # never returns, like a hidden OBS source
        self.got.append(text)

    async def close(self, code: int = 1000):
        self.closed = code


class SlowClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_stuck_client_does_not_hold_up_the_others(self):
        mgr = ConnectionManager()
        fast, stuck = FakeWS(), FakeWS(stuck=True)
        await mgr.connect(fast)
        await mgr.connect(stuck)
        started = time.monotonic()
        for i in range(mgr.SEND_QUEUE_MAX + 50):
            await mgr.broadcast({"type": "chat", "n": i})
        self.assertLess(time.monotonic() - started, 2.0)     # broadcast never waited on the stuck one
        await asyncio.wait_for(mgr.flush(), timeout=5)
        self.assertEqual(len(fast.got), mgr.SEND_QUEUE_MAX + 50)
        self.assertNotIn(stuck, mgr.active)                  # cut off once it fell too far behind
        self.assertEqual(mgr.dropped_slow, 1)
        await asyncio.sleep(0)
        self.assertEqual(stuck.closed, 1013)
        mgr.disconnect(fast)

    async def test_send_that_hangs_is_cut_off(self):
        mgr = ConnectionManager()
        mgr.SEND_TIMEOUT_SEC = 0.05
        stuck = FakeWS(stuck=True)
        await mgr.connect(stuck)
        await mgr.broadcast({"type": "chat"})
        for _ in range(50):
            if stuck not in mgr.active:
                break
            await asyncio.sleep(0.02)
        self.assertNotIn(stuck, mgr.active)

    async def test_messages_arrive_in_order(self):
        mgr = ConnectionManager()
        ws = FakeWS()
        await mgr.connect(ws)
        for i in range(20):
            await mgr.broadcast({"n": i})
        await mgr.flush()
        self.assertEqual([int(t.split(":")[1].strip(" }")) for t in ws.got], list(range(20)))
        mgr.disconnect(ws)


class RedFlagPatternTests(unittest.TestCase):
    def test_one_pattern_still_names_the_phrase(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        phrases = [f"word{i}" for i in range(300)] + ["buy followers"]
        flags = RedFlags(Store(Path(tmp.name) / "t.db"), {"phrases": phrases})
        self.assertIsNotNone(flags._any)
        self.assertEqual(flags.match("cheap BUY followers here"), "buy followers")
        self.assertEqual(flags.match("I said word42 twice"), "word42")
        self.assertIsNone(flags.match("hello there"))
        flags.configure({"phrases": []})
        self.assertIsNone(flags._any)
        self.assertIsNone(flags.match("buy followers"))


class PictureLinkFileTests(unittest.TestCase):
    def test_prune_drops_old_and_keeps_newest(self):
        now = 1_000_000_000.0
        cache = {"old": {"url": "a", "ts": now - avatar_link_file.KEEP_SEC - 1}}
        cache.update({f"u{i}": {"url": "b", "ts": now - i} for i in range(10)})
        out = avatar_link_file.prune(cache, now=now, max_entries=4)
        self.assertEqual(sorted(out), ["u0", "u1", "u2", "u3"])

    def test_twitch_file_saved_at_most_every_few_seconds(self):
        from adapters.twitch_avatars import TwitchAvatars

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "twitch_avatars.json"
        a = TwitchAvatars(path=path)
        writes = []
        with mock.patch.object(avatar_link_file, "write", side_effect=lambda p, c: writes.append(len(c))):
            for i in range(5):
                a._cache[str(i)] = {"url": "x", "ts": time.time()}
                a._dirty = True
                a.save_soon()
            self.assertEqual(len(writes), 1)      # the first one, then wait
            a.stop()                              # Core stopping writes the rest
            self.assertEqual(writes[-1], 5)


if __name__ == "__main__":
    unittest.main()
