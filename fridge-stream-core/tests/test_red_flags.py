"""Red flags: phrases flag a chatter, who is then kept off the overlays. Run from fridge-stream-core:

    python -m unittest tests.test_red_flags -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.red_flags import RedFlags, compile_phrase, matching_recent, parse_phrases  # noqa: E402
from core.store import Store  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def chat(name: str, text: str, uid: str = "", platform: Platform = Platform.KICK, mod: bool = False,
         badges: list | None = None) -> ChatEvent:
    user = ChatUser(platform=platform, id=uid or name, username=name, display_name=name.title(),
                    is_mod=mod, badges=badges or [])
    return ChatEvent(platform=platform, user=user, message=text)


class PhraseMatching(unittest.TestCase):
    def flags(self, phrases):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return RedFlags(Store(Path(tmp.name) / "t.db"), {"phrases": phrases})

    def test_case_and_spaces(self):
        rf = self.flags(["Free Followers"])
        self.assertEqual(rf.match("get FREE   followers now"), "Free Followers")
        self.assertIsNone(rf.match("followers for free"))

    def test_whole_words(self):
        rf = self.flags(["ass"])
        self.assertIsNone(rf.match("first class seats"))
        self.assertEqual(rf.match("what an ass!"), "ass")

    def test_wildcard(self):
        rf = self.flags(["scam*"])
        self.assertEqual(rf.match("total SCAMMER here"), "scam*")
        self.assertIsNone(rf.match("unscammable"))
        self.assertIsNotNone(compile_phrase("f*ck").search("fuuuck"))

    def test_symbols_and_tricks(self):
        rf = self.flags(["@everyone", "bigfollows"])
        self.assertEqual(rf.match("hey @everyone!!"), "@everyone")
        # zero-width space and fullwidth letters don't sneak past
        self.assertEqual(rf.match("check big​follows .com"), "bigfollows")
        self.assertEqual(rf.match("ｂｉｇｆｏｌｌｏｗｓ"), "bigfollows")

    def test_parse_phrases(self):
        self.assertEqual(parse_phrases("a\n\n  b  c \nA\n*\n"), ["a", "b c"])
        self.assertEqual(parse_phrases(["x", "X", " y "]), ["x", "y"])


class FlagList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db", None, {"enabled": True})
        self.rf = RedFlags(self.store, {"phrases": ["buy viewers"]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_phrase_flags_then_hides_everything(self):
        self.assertIsNone(run(self.rf.check(chat("amy", "hello"))))
        res = run(self.rf.check(chat("spammer", "BUY viewers at x.com", uid="42")))
        self.assertTrue(res["new"])
        self.assertEqual(res["flag"]["phrase"], "buy viewers")
        later = run(self.rf.check(chat("spammer", "innocent line", uid="42")))
        self.assertEqual(later, {"new": False, "flag": None})
        # same account after a name change, and a different platform stays separate
        self.assertTrue(self.rf.hides("kick", "42", "renamed"))
        self.assertFalse(self.rf.hides("twitch", "99", "someone"))
        rows = run(self.rf.list())
        self.assertEqual(len(rows), 1)
        # survives a restart
        again = RedFlags(self.store, {})
        self.assertTrue(again.is_flagged("kick", "42"))

    def test_mods_and_streamer_skipped(self):
        self.assertIsNone(run(self.rf.check(chat("modo", "don't buy viewers", mod=True))))
        self.assertIsNone(run(self.rf.check(chat("me", "never buy viewers", badges=["broadcaster"]))))
        self.rf.configure({"phrases": ["buy viewers"], "skip_mods": False})
        self.assertIsNotNone(run(self.rf.check(chat("modo", "don't buy viewers", mod=True))))

    def test_disabled_hides_nobody(self):
        run(self.rf.check(chat("spammer", "buy viewers", uid="42")))
        self.rf.configure({"phrases": ["buy viewers"], "enabled": False})
        self.assertIsNone(run(self.rf.check(chat("spammer", "hi", uid="42"))))
        self.assertIsNone(run(self.rf.check(chat("other", "buy viewers"))))
        self.assertFalse(self.rf.hides("kick", "42"))
        self.assertTrue(self.rf.is_flagged("kick", "42"))

    def test_manual_name_any_platform_and_unflag(self):
        row = run(self.rf.flag("", "", "TrollFace", "TrollFace"))
        self.assertTrue(self.rf.hides("twitch", "7", "trollface"))
        self.assertTrue(self.rf.hides("youtube", "", "TROLLFACE"))
        run(self.rf.unflag(row["id"]))
        self.assertFalse(self.rf.hides("twitch", "7", "trollface"))
        self.assertIsNone(run(self.rf.unflag(row["id"])))

    def test_chat_log_marks_flagged(self):
        for ev in (chat("amy", "hi"), chat("spammer", "buy viewers", uid="42"), chat("spammer", "more", uid="42")):
            run(self.store.process_chat(ev))
        run(self.rf.check(chat("spammer", "buy viewers", uid="42")))
        rows = run(self.store.search_chat())
        self.assertEqual({r["username"]: bool(r["flagged"]) for r in rows}, {"amy": False, "spammer": True})
        only = run(self.store.search_chat(flagged_only=True))
        self.assertEqual(len(only), 2)
        self.assertEqual(run(self.rf.list())[0]["messages"], 2)

    def test_matching_recent(self):
        items = [
            {"platform": "kick", "user": {"id": "1", "username": "a", "display_name": "A"}},
            {"platform": "twitch", "user": {"id": "1", "username": "b", "display_name": "B"}},
            {"platform": "twitch", "user": {"id": "5", "username": "c", "display_name": "Cee"}},
        ]
        self.assertEqual(len(matching_recent(items, "kick", "1")), 1)
        self.assertEqual(len(matching_recent(items, "", "", "cee")), 1)
        self.assertEqual(len(matching_recent(items, "twitch", "", "a")), 0)


class CoreHidesFlagged(unittest.TestCase):
    def test_flagged_chat_never_broadcast(self):
        from main import StreamCore

        core = StreamCore({})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core.store = Store(Path(tmp.name) / "t.db", None, {"enabled": True})
        core.red_flags = RedFlags(core.store, {})
        core.state.config = {"red_flags": {"phrases": ["buy viewers"]}}
        sent: list = []

        class WS:
            async def broadcast(self, payload):
                sent.append(payload)

            def push_roster(self, fn):
                pass

        core.state.ws_manager = WS()

        async def go():
            await core._on_chat(chat("spammer", "hello all", uid="42"))
            await core._on_chat(chat("amy", "hi", uid="1"))
            await core._on_chat(chat("spammer", "buy viewers cheap", uid="42"))
            await core._on_chat(chat("spammer", "still here", uid="42"))
            await core._on_alert({"kind": "subscribe", "platform": "kick", "username": "spammer",
                                  "headline": "spammer subscribed!"})

        run(go())
        texts = [p["data"]["message"] for p in sent if p["type"] == "chat"]
        self.assertEqual(texts, ["hello all", "hi"])
        hidden = [p["data"] for p in sent if p["type"] == "chat_user_hidden"]
        self.assertEqual(len(hidden), 1)
        self.assertEqual((hidden[0]["platform"], hidden[0]["id"]), ("kick", "42"))
        self.assertFalse([p for p in sent if p["type"] == "alert"])
        # the catch-up history new overlays get has lost the earlier line too
        self.assertEqual([c["message"] for c in core.recent_chat], ["hi"])
        # still in the chat log
        logged = run(core.store.search_chat(flagged_only=True))
        self.assertEqual(len(logged), 3)


class AdminRoutes(unittest.TestCase):
    def test_red_flag_endpoints(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.admin_routes import create_admin_router
        from api.server import CoreState

        token = "unit-test-admin-token-123456"
        disk = {"points": {"admin_token": token}}

        def load():
            return json.loads(json.dumps(disk))

        def save(cfg, path=None):
            disk.clear()
            disk.update(json.loads(json.dumps(cfg)))

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(Path(tmp.name) / "t.db", None, {"enabled": True})
        state = CoreState()
        state.config = load()
        state.store = store
        state.red_flags = RedFlags(store, {})
        hidden = []

        async def hide(platform, uid, username, display_name=""):
            hidden.append((platform, username))
            return 0

        state.red_flag_hide = hide
        app = FastAPI()
        app.include_router(create_admin_router(state))
        hdr = {"X-Admin-Token": token}
        with mock.patch("api.admin_routes.load_config", load), mock.patch("api.admin_routes.save_config", save):
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/admin/red-flags").status_code, 401)
                d = client.get("/api/admin/red-flags", headers=hdr).json()
                self.assertTrue(d["enabled"])
                self.assertEqual(d["phrases"], [])
                d = client.put("/api/admin/red-flags", headers=hdr,
                               json={"phrases": "Buy Viewers\n\nbuy viewers\nscam*", "skip_mods": False}).json()
                self.assertEqual(d["phrases"], ["Buy Viewers", "scam*"])
                self.assertFalse(d["skip_mods"])
                self.assertEqual(disk["red_flags"]["phrases"], ["Buy Viewers", "scam*"])
                self.assertEqual(state.red_flags.match("buy  viewers"), "Buy Viewers")
                # a stale copy of the whole config form must not undo the phrases
                stale = load()
                stale["red_flags"] = {"phrases": []}
                self.assertEqual(client.put("/api/admin/config", headers=hdr, json={"config": stale}).status_code, 200)
                self.assertEqual(disk["red_flags"]["phrases"], ["Buy Viewers", "scam*"])
                # by hand: "twitch:name" works too
                d = client.post("/api/admin/red-flags/flag", headers=hdr, json={"name": "@twitch:Troll"}).json()
                self.assertEqual(len(d["flagged"]), 1)
                self.assertEqual(hidden, [("twitch", "troll")])
                self.assertTrue(state.red_flags.hides("twitch", "", "TROLL"))
                self.assertEqual(client.post("/api/admin/red-flags/flag", headers=hdr,
                                             json={"name": "x", "platform": "myspace"}).status_code, 400)
                fid = d["flagged"][0]["id"]
                d = client.delete(f"/api/admin/red-flags/{fid}", headers=hdr).json()
                self.assertEqual(d["flagged"], [])
                self.assertEqual(client.delete(f"/api/admin/red-flags/{fid}", headers=hdr).status_code, 404)
                rows = client.get("/api/admin/chat", headers=hdr, params={"flagged": 1}).json()
                self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
