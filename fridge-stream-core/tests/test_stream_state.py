"""Stream start / end (core/stream_state.py), the companion bot link (core/companion_link.py),
how main.py uses them (new credits session on go-live, alerts to the companion) and their
dashboard routes (api/companion_routes.py). Nothing here touches the network or the real
data/ folder. Run from fridge-stream-core:

    python -m unittest tests.test_stream_state -v
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.companion_link import CompanionLink, alert_brief, public_settings, read_settings  # noqa: E402
from core.stream_state import StreamState  # noqa: E402
from core.stream_state import read_settings as stream_settings  # noqa: E402


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class StreamRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"stream": {"restart_grace_min": 15}}
        self.clock = Clock()
        self.events = []
        self.st = self.make()

    def make(self):
        st = StreamState(lambda: self.cfg, Path(self.tmp.name), clock=self.clock)
        st.add_listener(lambda c: self.events.append((c["event"], tuple(c["platforms"]))))
        return st

    def test_first_live_starts_last_offline_drops_then_ends(self):
        st, clock = self.st, self.clock
        st.report("youtube", True, "chat")
        st.report("twitch", True, "eventsub")
        st.report("twitch", True, "eventsub")          # repeats do nothing
        st.report("kick", False, "poll")               # a platform that was never live: nothing
        self.assertEqual(self.events, [("started", ("youtube",))])
        self.assertEqual(st.status()["platforms"], ["twitch", "youtube"])
        clock.t += 3600
        st.report("youtube", False)
        self.assertEqual(st.status()["state"], "live")   # Twitch still live
        st.report("twitch", False)
        self.assertEqual(self.events[-1], ("dropped", ()))
        self.assertEqual(st.status()["state"], "dropped")
        self.assertEqual(st.status()["ends_in"], 900)
        clock.t += 899
        st.check()
        self.assertTrue(st.live)
        clock.t += 1
        st.check()
        self.assertFalse(st.live)
        self.assertEqual(self.events[-1][0], "ended")
        self.assertEqual(st.ended_at, 1000 + 3600)      # the end is when it dropped, not the timer

    def test_short_drop_is_the_same_stream(self):
        st = self.st
        st.report("kick", True)
        st.report("kick", False)
        self.clock.t += 600
        st.report("kick", True)
        self.assertEqual([e for e, _ in self.events], ["started", "dropped", "resumed"])
        self.assertEqual((st.session, st.restarts), (1, 1))
        st.report("kick", False)
        self.clock.t += 901
        st.check()
        st.report("kick", True)                         # after the window: a new stream
        self.assertEqual(self.events[-1][0], "started")
        self.assertEqual(st.session, 2)

    def test_zero_grace_ends_at_once(self):
        self.cfg = {"stream": {"restart_grace_min": 0}}
        self.st.report("twitch", True)
        self.st.report("twitch", False)
        self.assertEqual([e for e, _ in self.events], ["started", "ended"])

    def test_restart_mid_stream_resumes_and_a_late_start_ends(self):
        self.st.report("twitch", True)
        self.clock.t += 120
        self.st.tick()                                  # "still live" noted
        again = self.make()                             # Core restarted
        self.assertTrue(again.live)
        again.resume_timer()
        self.clock.t += 60
        again.report("twitch", True)
        self.assertEqual(self.events[-1][0], "resumed")
        self.assertEqual(again.session, 1)
        # Core closed mid-stream and opened the next day: that stream ends, a new one starts
        self.clock.t += 86400
        late = self.make()
        late.resume_timer()
        self.assertFalse(late.live)
        self.assertEqual(self.events[-1][0], "ended")
        late.report("twitch", True)
        self.assertEqual((self.events[-1][0], late.session), ("started", 2))

    def test_settings_clamp(self):
        self.assertEqual(stream_settings({})["restart_grace_min"], 15)
        self.assertEqual(stream_settings({"stream": {"restart_grace_min": "x"}})["restart_grace_min"], 15)
        self.assertEqual(stream_settings({"stream": {"restart_grace_min": 999}})["restart_grace_min"], 120)

    def test_unknown_platform_ignored(self):
        self.st.report("tiktok", True)
        self.assertEqual(self.events, [])


class Link(unittest.TestCase):
    def setUp(self):
        self.cfg = {"companion": {"enabled": True, "url": "192.168.1.5:3870/", "key": "pw"}}
        self.sent = []
        self.answer = 200

        async def post(url, body, headers):
            self.sent.append((url, body["type"], headers["Authorization"]))
            return self.answer, {"ok": True}

        async def snap():
            return {"points": [{"name": "Amy", "points": 5}]}

        self.link = CompanionLink(lambda: self.cfg, heartbeat=lambda: {"stream": {"live": False}},
                                  snapshot=snap, post=post)

    def test_settings(self):
        s = read_settings(self.cfg)
        self.assertEqual(s["url"], "http://192.168.1.5:3870")
        self.assertEqual(s["heartbeat_sec"], 30)
        pub = public_settings(s)
        self.assertNotIn("key", pub)
        self.assertTrue(pub["key_set"])
        self.assertFalse(read_settings({})["enabled"])

    def test_off_sends_nothing(self):
        self.cfg["companion"]["enabled"] = False
        self.link.send("stream", {})
        self.assertEqual(len(self.link._queue), 0)
        self.assertIn("off", run(self.link.test())["message"])

    def test_queue_replaces_heartbeats_and_keeps_events(self):
        for _ in range(3):
            self.link.send("heartbeat", {})
        self.link.stream_changed({"event": "started"})
        self.link.alert({"kind": "follow"})               # follows never go
        self.link.alert({"kind": "raid", "viewers": 30, "is_test": True})   # tests never go
        self.link.alert({"kind": "raid", "viewers": 30, "display_name": "Bo", "message": "x" * 500})
        self.assertEqual([m["type"] for m in self.link._queue], ["heartbeat", "stream", "alert"])
        self.assertEqual(len(self.link._queue[2]["data"]["message"]), 200)

    def test_delivery_and_retry(self):
        async def go():
            self.answer = 401
            self.link.start()
            await asyncio.sleep(0.05)
            self.assertEqual(self.link.state, "retrying")
            self.assertIn("password", self.link.message)
            self.answer = 200
            await self.link.stop()
            self.link.start()
            await asyncio.sleep(0.05)
            await self.link.stop()

        run(go())
        self.assertEqual(self.link.state, "on")
        self.assertEqual(self.sent[0], ("http://192.168.1.5:3870/core/push", "hello", "Bearer pw"))
        types = [t for _, t, _ in self.sent]
        self.assertIn("heartbeat", types)
        self.assertIn("snapshot", types)
        self.assertEqual(len(self.link._queue), 0)

    def test_alert_brief(self):
        self.assertIsNone(alert_brief({"kind": "sub", "is_test": True}))
        b = alert_brief({"kind": "gift", "qty": 10, "display_name": "Amy", "platform": "twitch", "user_id": "1"})
        self.assertEqual(b, {"kind": "gift", "qty": 10, "display_name": "Amy", "platform": "twitch"})


def run(coro):
    return asyncio.run(coro)


class CoreWiring(unittest.TestCase):
    def test_go_live_starts_a_new_credits_session_only_when_on(self):
        from main import StreamCore

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core = StreamCore({})
        core.state.config = {"credits": {"enabled": True}, "stream": {"restart_grace_min": 15}}
        core.credits.session_path = Path(tmp.name) / "credits.json"
        # a private copy of the stream state (never the real data/ folder)
        core.stream = StreamState(lambda: core.state.config, Path(tmp.name))
        core.stream.add_listener(core._stream_changed)
        notes = []
        core.bus.note = lambda kind, text, platform="": notes.append((kind, text))
        core.credits.chatters["twitch:amy"] = object()
        core.stream.report("twitch", True)
        self.assertIn("twitch:amy", core.credits.chatters)     # switch off: kept
        core.stream.report("twitch", False)
        core.stream.report("twitch", True)
        core.state.config["credits"]["auto_session"] = True
        core.stream.report("twitch", False)
        core.stream.clock = lambda: 10 ** 12                    # long after: the next live is a new stream
        core.stream.check()
        core.stream.report("twitch", True)
        self.assertEqual(core.credits.chatters, {})
        kinds = [k for k, _ in notes]
        self.assertTrue(all(k == "stream" for k in kinds))
        self.assertIn("New credits session", notes[-1][1])
        self.assertTrue(any("Back live" in t for _, t in notes))

    def test_heartbeat_and_snapshot(self):
        from main import StreamCore

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core = StreamCore({})
        core.stream = StreamState(lambda: {}, Path(tmp.name))
        beat = core._companion_heartbeat()
        self.assertEqual(beat["stream"]["state"], "offline")
        self.assertIn("viewers", beat)

        class FakeStore:
            async def list_users(self, limit=100):
                return [{"display_name": "Amy", "points": 12, "accounts": "twitch:amy"}]

        core.store = FakeStore()
        core.state.config = {"companion": {"send_queue": False}}
        snap = run(core._companion_snapshot())
        self.assertEqual(snap, {"points": [{"name": "Amy", "points": 12, "accounts": "twitch:amy"}]})


class Routes(unittest.TestCase):
    def test_stream_and_companion_routes(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import api.companion_routes as routes

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        TOKEN = "tok-123456789abc"
        state = type("S", (), {})()
        state.config = {"points": {"admin_token": TOKEN}, "credits": {"enabled": True, "title": "Hi"}}
        state.stream = StreamState(lambda: state.config, Path(tmp.name))
        restarted = []
        state.companion = type("L", (), {"status": lambda self: {"state": "off"},
                                         "restart": lambda self: restarted.append(1)})()
        saved = {}
        real_save = routes.save_config
        self.addCleanup(setattr, routes, "save_config", real_save)
        routes.save_config = lambda cfg: saved.update(cfg)
        app = FastAPI()
        app.include_router(routes.create_companion_router(state, Path(tmp.name)))
        c = TestClient(app)
        head = {"X-Admin-Token": TOKEN}
        self.assertEqual(c.get("/api/admin/stream").status_code, 401)
        r = c.get("/api/admin/stream", headers=head).json()
        self.assertEqual(r["settings"], {"auto_session": False, "restart_grace_min": 15.0})
        r = c.put("/api/admin/stream/settings", headers=head, json={"auto_session": True, "restart_grace_min": 5}).json()
        self.assertEqual(saved["credits"], {"enabled": True, "title": "Hi", "auto_session": True})
        self.assertEqual(r["settings"]["restart_grace_min"], 5.0)
        r = c.put("/api/admin/companion/settings", headers=head,
                  json={"enabled": True, "url": "10.0.0.2:3870", "key": "secret", "key_set": True}).json()
        self.assertEqual(saved["companion"]["key"], "secret")
        self.assertNotIn("key", r["settings"])
        self.assertTrue(r["settings"]["key_set"])
        c.put("/api/admin/companion/settings", headers=head, json={"heartbeat_sec": 60})
        self.assertEqual(saved["companion"]["key"], "secret")        # kept when not typed again
        c.put("/api/admin/companion/settings", headers=head, json={"key_clear": True})
        self.assertEqual(saved["companion"]["key"], "")
        self.assertEqual(len(restarted), 3)


if __name__ == "__main__":
    unittest.main()
