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

    def test_chat_log_only_flagged(self):
        self.store.configure_chat_log({"enabled": True, "only_flagged": True})
        run(self.store.process_chat(chat("amy", "hi")))
        run(self.store.process_chat(chat("spammer", "buy viewers", uid="42"), award=False, flagged=True))
        self.assertEqual([r["username"] for r in run(self.store.search_chat())], ["spammer"])
        self.store.configure_chat_log({"enabled": False, "only_flagged": True})
        run(self.store.process_chat(chat("spammer", "more", uid="42"), award=False, flagged=True))
        self.assertEqual(len(run(self.store.search_chat())), 1)

    def test_matching_recent(self):
        items = [
            {"platform": "kick", "user": {"id": "1", "username": "a", "display_name": "A"}},
            {"platform": "twitch", "user": {"id": "1", "username": "b", "display_name": "B"}},
            {"platform": "twitch", "user": {"id": "5", "username": "c", "display_name": "Cee"}},
        ]
        self.assertEqual(len(matching_recent(items, "kick", "1")), 1)
        self.assertEqual(len(matching_recent(items, "", "", "cee")), 1)
        self.assertEqual(len(matching_recent(items, "twitch", "", "a")), 0)


class CheckPastChat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db", None, {"enabled": True})
        self.rf = RedFlags(self.store, {})

    def tearDown(self):
        self.tmp.cleanup()

    def log(self, *events):
        for ev in events:
            run(self.store.process_chat(ev))

    def test_finds_earlier_lines_and_groups_them(self):
        self.log(chat("amy", "hello"), chat("spammer", "buy viewers here", uid="42"),
                 chat("spammer", "BUY   VIEWERS cheap", uid="42"), chat("spammer", "hi", uid="42"),
                 chat("bob", "total scammer", platform=Platform.TWITCH))
        self.rf.configure({"phrases": ["buy viewers", "scam*"]})
        res = run(self.rf.scan_past())
        self.assertEqual(res["scanned"], 5)
        self.assertFalse(res["more"])
        found = {p["username"]: p for p in res["people"]}
        self.assertEqual(set(found), {"spammer", "bob"})
        self.assertEqual(found["spammer"]["count"], 2)
        self.assertEqual(found["spammer"]["message"], "buy viewers here")
        self.assertEqual(found["spammer"]["phrase"], "buy viewers")
        self.assertEqual(len(found["spammer"]["examples"]), 2)
        self.assertEqual((found["bob"]["platform"], found["bob"]["phrase"]), ("twitch", "scam*"))
        # nobody is flagged by looking
        self.assertEqual(run(self.rf.list()), [])

    def test_no_phrases_reads_nothing(self):
        self.log(chat("amy", "hello"))
        self.assertEqual(run(self.rf.scan_past()), {"scanned": 0, "people": [], "more": False})

    def test_skips_flagged_mods_and_staff(self):
        self.log(chat("spammer", "buy viewers", uid="42"), chat("modo", "don't buy viewers", uid="7"),
                 chat("me", "never buy viewers", uid="1"), chat("other", "buy viewers", uid="9"))
        self.rf.configure({"phrases": ["buy viewers"]})
        run(self.rf.flag("kick", "42", "spammer", "Spammer"))
        # modo had a mod badge in live chat since Core started; "me" is Core's own staff
        run(self.rf.check(chat("modo", "hello", uid="7", mod=True)))
        self.rf.staff = lambda plat, uid, name: name == "me"
        names = [p["username"] for p in run(self.rf.scan_past())["people"]]
        self.assertEqual(names, ["other"])
        self.rf.configure({"phrases": ["buy viewers"], "skip_mods": False})
        names = {p["username"] for p in run(self.rf.scan_past())["people"]}
        self.assertEqual(names, {"modo", "me", "other"})

    def test_list_is_capped(self):
        self.log(*(chat(f"bot{i}", "buy viewers", uid=str(i)) for i in range(5)))
        self.rf.configure({"phrases": ["buy viewers"]})
        res = self.rf.scan_past_sync(self.store.iter_chat_sync(batch=2), max_people=3)
        self.assertEqual(len(res["people"]), 3)
        self.assertTrue(res["more"])
        self.assertEqual(res["scanned"], 5)

    def test_core_knows_its_staff(self):
        from main import StreamCore

        core = StreamCore({"permissions": {"mod": ["twitch:helper"]}})
        core.state.config = {"kick": {"channel_slug": "MyChannel"}, "twitch": {"channel": "YOUR_TWITCH_CHANNEL"}}
        self.assertTrue(core._is_staff("kick", "5", "mychannel"))
        self.assertTrue(core._is_staff("twitch", "6", "helper"))
        self.assertFalse(core._is_staff("kick", "6", "helper"))
        self.assertFalse(core._is_staff("twitch", "8", "your_twitch_channel"))
        self.assertFalse(core._is_staff("myspace", "1", "x"))


class CoreHidesFlagged(unittest.TestCase):
    def test_flagged_chat_never_broadcast(self):
        from main import StreamCore

        core = StreamCore({})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core.store = Store(Path(tmp.name) / "t.db", None, {"enabled": True})
        core.red_flags = RedFlags(core.store, {})
        core.state.config = {"red_flags": {"phrases": ["buy viewers"]},
                             "chat_log": {"enabled": True, "only_flagged": True}}
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
        # still in the chat log, and (only_flagged) nobody else is
        logged = run(core.store.search_chat())
        self.assertEqual([r["message"] for r in logged], ["still here", "buy viewers cheap"])


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
                # check past chat: lists, flags nobody; then flag the ticked ones
                for ev in (chat("old", "buy viewers please", uid="77"), chat("nice", "hi", uid="78")):
                    run(store.process_chat(ev))
                d = client.post("/api/admin/red-flags/check-past", headers=hdr).json()
                self.assertEqual(d["scanned"], 2)
                self.assertEqual([p["username"] for p in d["people"]], ["old"])
                self.assertEqual(client.get("/api/admin/red-flags", headers=hdr).json()["flagged"], [])
                d = client.post("/api/admin/red-flags/apply-past", headers=hdr, json={"people": d["people"]}).json()
                self.assertEqual(d["flagged_now"], 1)
                self.assertEqual((d["flagged"][0]["source"], d["flagged"][0]["phrase"]), ("past", "Buy Viewers"))
                self.assertEqual(hidden[-1], ("kick", "old"))
                self.assertTrue(state.red_flags.hides("kick", "77"))
                self.assertEqual(client.post("/api/admin/red-flags/check-past", headers=hdr).json()["people"], [])
                self.assertEqual(client.post("/api/admin/red-flags/apply-past", headers=hdr, json={}).status_code, 400)
                client.put("/api/admin/red-flags", headers=hdr, json={"phrases": ""})
                self.assertEqual(client.post("/api/admin/red-flags/check-past", headers=hdr).status_code, 400)


if __name__ == "__main__":
    unittest.main()
