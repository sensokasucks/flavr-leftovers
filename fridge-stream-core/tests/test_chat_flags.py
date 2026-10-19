"""Custom chat flags: the streamer's own flags with their own phrases and actions. Run from
fridge-stream-core:

    python -m unittest tests.test_chat_flags -v
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

from core.chat_flags import ChatFlags, normalize_custom  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.red_flags import RedFlags  # noqa: E402
from core.store import Store  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def chat(name: str, text: str, uid: str = "", platform: Platform = Platform.KICK, mod: bool = False) -> ChatEvent:
    user = ChatUser(platform=platform, id=uid or name, username=name, display_name=name.title(), is_mod=mod)
    return ChatEvent(platform=platform, user=user, message=text)


class Settings(unittest.TestCase):
    def test_normalize(self):
        """Saved flags are cleaned: ids from names, duplicate phrases dropped, numbers clamped."""
        flags = normalize_custom([
            {"name": "  Giveaway   entry ", "phrases": "enter me\n\nENTER ME\ngiveaway*", "points": "25"},
            {"name": "Giveaway entry"},          # same name: its own id
            {"name": ""},                        # no name: dropped
            {"name": "Red", "points": 10 ** 9, "cooldown_sec": -4},
            "junk",
        ])
        self.assertEqual([f["id"] for f in flags], ["giveaway-entry", "giveaway-entry-2", "red-1"])
        self.assertEqual(flags[0]["name"], "Giveaway entry")
        self.assertEqual(flags[0]["phrases"], ["enter me", "giveaway*"])
        self.assertEqual(flags[0]["points"], 25)
        self.assertTrue(flags[0]["log"])          # defaults filled in
        self.assertFalse(flags[0]["hide"])
        self.assertEqual(flags[2]["points"], 1_000_000)
        self.assertEqual(flags[2]["cooldown_sec"], 0)
        # an id once given stays, even when the name changes
        self.assertEqual(normalize_custom([{"id": "giveaway-entry", "name": "Raffle"}])[0]["id"], "giveaway-entry")
        self.assertEqual(normalize_custom("nope"), [])


class Matching(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / "t.db")
        self.rf = RedFlags(self.store, {})

    def flags(self, **extra):
        return ChatFlags(self.store, self.rf, [{"name": "Giveaway", "phrases": ["enter me"], **extra}])

    def test_first_time_then_quiet(self):
        cf = self.flags()
        hits = run(cf.check(chat("amy", "please ENTER me")))
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]["first"])
        self.assertEqual(hits[0]["phrase"], "enter me")
        self.assertTrue(cf.on_list("giveaway", "kick", "amy"))
        self.assertEqual(run(cf.check(chat("amy", "enter me again"))), [])
        self.assertEqual(run(cf.check(chat("bob", "hello"))), [])
        rows = run(cf.list())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hits"], 2)       # the second line still counts
        self.assertEqual(cf.flags_for("kick", "", "AMY"), ["giveaway"])
        self.assertTrue(cf.keeps_log("kick", "amy"))

    def test_every_time_with_cooldown(self):
        cf = self.flags(every_time=True, cooldown_sec=60)
        self.assertEqual(len(run(cf.check(chat("amy", "enter me")))), 1)
        self.assertEqual(run(cf.check(chat("amy", "enter me"))), [])     # within the cooldown
        cf._last.clear()
        hits = run(cf.check(chat("amy", "enter me")))
        self.assertEqual(len(hits), 1)
        self.assertFalse(hits[0]["first"])

    def test_mods_skipped_and_off(self):
        cf = self.flags()
        self.assertEqual(run(cf.check(chat("modd", "enter me", mod=True))), [])
        cf = ChatFlags(self.store, self.rf, [{"name": "Giveaway", "phrases": ["enter me"], "skip_mods": False}])
        self.assertEqual(len(run(cf.check(chat("modd", "enter me", mod=True)))), 1)
        cf = ChatFlags(self.store, self.rf, [{"name": "Off", "phrases": ["enter me"], "enabled": False}])
        self.assertEqual(run(cf.check(chat("amy", "enter me"))), [])

    def test_check_past(self):
        cf = self.flags()
        rows = [
            {"platform": "kick", "platform_user_id": "1", "username": "amy", "display_name": "Amy",
             "message": "enter me", "timestamp": 1.0},
            {"platform": "kick", "platform_user_id": "1", "username": "amy", "display_name": "Amy",
             "message": "pls enter me", "timestamp": 2.0},
            {"platform": "kick", "platform_user_id": "2", "username": "bob", "display_name": "Bob",
             "message": "hello", "timestamp": 3.0},
        ]
        res = cf.scan_past_sync("giveaway", rows)
        self.assertEqual(res["scanned"], 3)
        self.assertEqual([(p["username"], p["count"]) for p in res["people"]], [("amy", 2)])
        self.assertEqual(cf.scan_past_sync("nope", rows)["people"], [])

    def test_log_keeps_chat_with_chat_log_off(self):
        store = Store(Path(tempfile.mkdtemp()) / "t.db", None, {"enabled": False})
        run(store.process_chat(chat("amy", "not saved")))
        store.submit_chat(chat("amy", "saved"), keep=True)
        self.assertEqual([r["message"] for r in run(store.search_chat())], ["saved"])


class CoreActions(unittest.TestCase):
    def core(self, flags, chat_log=None):
        from main import StreamCore

        core = StreamCore({})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core.store = Store(Path(tmp.name) / "t.db", {"enabled": True}, {"enabled": False})
        core.red_flags = RedFlags(core.store, {})
        core.chat_flags = ChatFlags(core.store, core.red_flags, [])
        core.state.config = {"red_flags": {"custom": flags}, "chat_log": chat_log or {"enabled": False}}
        self.sent: list = []
        self.alerts: list = []
        self.replies: list = []
        self.flag_events: list = []
        sent = self.sent

        class WS:
            async def broadcast(self, payload):
                sent.append(payload)

            def push_roster(self, fn):
                pass

        core.state.ws_manager = WS()
        core.bus.on_reply(self._reply)
        core.bus.on_flag(self._flag)
        core.bus.on_alert(self._alert)
        return core

    async def _reply(self, r):
        self.replies.append(r)

    async def _flag(self, p):
        self.flag_events.append(p)

    async def _alert(self, p):
        self.alerts.append(p)

    def test_actions(self):
        """A matching flag runs its actions: alert, reply, points, reaction, game hook."""
        core = self.core([{"name": "Giveaway", "phrases": ["enter me"], "alert": True,
                           "alert_text": "{name} is in!", "reply": "@{name} you're in ({flag})",
                           "points": 25, "reaction": "boo"}])

        class Game:
            def __init__(self):
                self.got = []

            async def on_flag(self, payload):
                self.got.append(payload)

        game = Game()
        core.games = {"g": game}
        fired = []

        async def fire(entry, event, **kw):
            fired.append((entry["id"], entry["cost"], kw.get("free")))
            return {"ok": True}

        core.reactions.fire = fire
        with mock.patch.object(type(core.reactions), "cfg", new_callable=mock.PropertyMock) as cfg:
            cfg.return_value = {"entries": [{"id": "boo", "label": "Boo", "cost": 50, "permission": "sub"}]}

            async def go():
                await core._on_chat(chat("amy", "enter me pls", uid="7"))
                await core._on_chat(chat("amy", "enter me pls", uid="7"))     # once only
                await core._on_chat(chat("bob", "hi", uid="8"))

            run(go())
        self.assertEqual([p["data"]["message"] for p in self.sent if p["type"] == "chat"],
                         ["enter me pls", "enter me pls", "hi"])
        self.assertEqual(len(self.flag_events), 1)
        ev = self.flag_events[0]
        self.assertEqual((ev["flag"]["id"], ev["first"], ev["user"]["username"]), ("giveaway", True, "amy"))
        self.assertEqual(len(game.got), 1)
        self.assertEqual(len([p for p in self.sent if p["type"] == "chat_flag"]), 1)
        self.assertEqual([(a["kind"], a["headline"], a["title"]) for a in self.alerts],
                         [("flag", "Amy is in!", "Giveaway")])
        self.assertEqual([r.message for r in self.replies if r.source == "flag"], ["@Amy you're in (Giveaway)"])
        self.assertEqual(fired, [("boo", 0, True)])
        balance = run(core.store.get_balance_for_platform("kick", "7"))
        self.assertGreaterEqual(balance, 25)
        # log: on (default) keeps amy's lines although Save chat history is off
        logged = run(core.store.search_chat())
        self.assertEqual([r["message"] for r in logged], ["enter me pls", "enter me pls"])
        self.assertEqual(logged[0]["flags"], "giveaway")
        self.assertEqual([r["username"] for r in run(core.store.search_chat(flag="giveaway"))], ["amy", "amy"])

    def test_command_runs_as_streamer_with_their_name(self):
        core = self.core([{"name": "Spawn", "phrases": ["spawn me"], "command": "spawn zombie {user}"}])
        ran = []

        async def test_command(message, **kw):
            ran.append((message, kw["username"], kw["is_admin"], kw["dry_run"]))
            return {"ok": True}

        core.test_command = test_command
        run(core._on_chat(chat("amy; !ban x", "spawn me", uid="7")))
        self.assertEqual(ran, [("!spawn zombie amybanx", "amy; !ban x", True, False)])

    def test_hide_red_flags_them(self):
        core = self.core([{"name": "Spam", "phrases": ["buy viewers"], "hide": True, "alert": True,
                           "points": 10}], chat_log={"enabled": True})

        async def go():
            await core._on_chat(chat("spammer", "hello", uid="42"))
            await core._on_chat(chat("spammer", "buy viewers here", uid="42"))
            await core._on_chat(chat("spammer", "still here", uid="42"))

        run(go())
        self.assertEqual([p["data"]["message"] for p in self.sent if p["type"] == "chat"], ["hello"])
        self.assertEqual(len([p for p in self.sent if p["type"] == "chat_user_hidden"]), 1)
        self.assertFalse([p for p in self.sent if p["type"] == "chat_flag"])   # nothing to overlays
        self.assertEqual(len(self.flag_events), 1)                              # plugins still hear it
        self.assertTrue(self.flag_events[0]["hidden"])
        self.assertEqual(self.alerts, [])
        self.assertTrue(core.red_flags.hides("kick", "42"))
        row = run(core.red_flags.list())[0]
        self.assertEqual((row["source"], row["phrase"]), ("flag:spam", "buy viewers"))


class AdminRoutes(unittest.TestCase):
    def test_custom_flag_endpoints(self):
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
        state.chat_flags = ChatFlags(store, state.red_flags, [])
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
                d = client.get("/api/admin/red-flags", headers=hdr).json()
                self.assertEqual(d["custom"], [])
                d = client.put("/api/admin/red-flags", headers=hdr, json={"custom": [
                    {"name": "Giveaway", "phrases": "enter me"},
                    {"name": "Spam", "phrases": ["buy viewers"], "hide": True},
                ]}).json()
                self.assertEqual([f["id"] for f in d["custom"]], ["giveaway", "spam"])
                self.assertEqual(disk["red_flags"]["custom"][0]["phrases"], ["enter me"])
                self.assertEqual(client.put("/api/admin/red-flags", headers=hdr, json={"custom": "x"}).status_code, 400)
                # a stale config form save keeps the flags
                stale = load()
                stale["red_flags"] = {"phrases": []}
                self.assertEqual(client.put("/api/admin/config", headers=hdr, json={"config": stale}).status_code, 200)
                self.assertEqual(len(disk["red_flags"]["custom"]), 2)
                # by hand onto a custom flag; "spam" red-flags them too
                d = client.post("/api/admin/red-flags/flag", headers=hdr,
                                json={"name": "amy", "platform": "kick", "flag": "giveaway"}).json()
                self.assertEqual([(r["flag"], r["username"]) for r in d["custom_flagged"]], [("giveaway", "amy")])
                self.assertEqual(d["flagged"], [])
                d = client.post("/api/admin/red-flags/flag", headers=hdr,
                                json={"name": "troll", "platform": "kick", "flag": "spam"}).json()
                self.assertEqual(len(d["flagged"]), 1)
                self.assertEqual(hidden, [("kick", "troll")])
                self.assertEqual(client.post("/api/admin/red-flags/flag", headers=hdr,
                                             json={"name": "x", "flag": "nope"}).status_code, 404)
                # unflag + undo
                row = next(r for r in d["custom_flagged"] if r["username"] == "amy")
                d = client.delete(f"/api/admin/red-flags/custom/{row['id']}", headers=hdr).json()
                self.assertEqual([r["username"] for r in d["custom_flagged"]], ["troll"])
                self.assertEqual(client.delete(f"/api/admin/red-flags/custom/{row['id']}", headers=hdr).status_code, 404)
                d = client.post("/api/admin/red-flags/custom/restore", headers=hdr, json={"removed": d["removed"]}).json()
                self.assertEqual(len(d["custom_flagged"]), 2)
                # check past chat for one flag, then apply it
                for ev in (chat("old", "can you enter me", uid="77"), chat("nice", "hi", uid="78")):
                    run(store.process_chat(ev))
                d = client.post("/api/admin/red-flags/check-past", headers=hdr, json={"flag": "giveaway"}).json()
                self.assertEqual([p["username"] for p in d["people"]], ["old"])
                d = client.post("/api/admin/red-flags/apply-past", headers=hdr,
                                json={"people": d["people"], "flag": "giveaway"}).json()
                self.assertEqual(d["flagged_now"], 1)
                self.assertEqual(len(d["flagged"]), 1)                # giveaway doesn't red-flag
                rows = client.get("/api/admin/chat", headers=hdr, params={"flag": "giveaway"}).json()
                self.assertEqual([r["message"] for r in rows], ["can you enter me"])
                self.assertEqual(rows[0]["flags"], "giveaway")
                # red flag check-past still works without a body
                self.assertEqual(client.post("/api/admin/red-flags/check-past", headers=hdr).status_code, 400)
                # deleting a flag clears its list
                d = client.put("/api/admin/red-flags", headers=hdr,
                               json={"custom": [{"id": "spam", "name": "Spam", "phrases": ["buy viewers"]}]}).json()
                self.assertEqual({r["flag"] for r in d["custom_flagged"]}, {"spam"})
                self.assertEqual({r["flag"] for r in run(state.chat_flags.list())}, {"spam"})


if __name__ == "__main__":
    unittest.main()
