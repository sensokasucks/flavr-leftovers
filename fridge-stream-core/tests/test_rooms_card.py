"""Live page "Stream Rooms" card (work list item 13): the game's rooms_state packet
(core/reactions.py clean_rooms_state) and the card's commands (ROOMS_ACTIONS, GET / POST
/api/admin/rooms in api/admin_routes.py). Run from fridge-stream-core:

    python -m unittest tests.test_rooms_card -v
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

from tests.test_reactions import FakeWS, Harness  # noqa: E402
from core.reactions import ROOMS_ACTIONS, clean_rooms_state  # noqa: E402

TOKEN = "unit-test-admin-token-123456"
HEAD = {"X-Admin-Token": TOKEN}

STATE = {"room": "lecture_hall", "rooms": [["lecture_hall", "Lecture hall"], ["theater", "Theater"]],
         "paused": False, "focus": False, "clean": False, "curtain": "open", "playing": True,
         "views": [{"id": "b0", "name": "Wide", "key": 1}], "screen": {"mode": "capture", "text": "Sharing a tab", "ok": True},
         "sender": {"connected": True, "sharing": True, "label": "YouTube", "fps": 30, "audio": True},
         "volume": 0.8, "ambience": 0.5, "presenters": [], "costream": {"role": "off"}}


def run(coro):
    return asyncio.run(coro)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.h = Harness(Path(self.tmp.name))
        self.ws = FakeWS()

    def hello(self):
        run(self.h.eng.on_client_message(self.ws, {"type": "hello", "data": {"client": "stream_rooms"}}))

    def test_state_needs_hello_and_is_cleaned(self):
        eng = self.h.eng
        run(eng.on_client_message(self.ws, {"type": "rooms_state", "data": STATE}))
        self.assertIsNone(eng.rooms_state)               # an overlay page can't pose as the game
        self.hello()
        run(eng.on_client_message(self.ws, {"type": "rooms_state", "data": {**STATE, "evil": "x", "curtain": "closed"}}))
        self.assertEqual(eng.rooms_state["room"], "lecture_hall")
        self.assertNotIn("evil", eng.rooms_state)
        self.assertEqual(eng.stage_state["curtain"], "closed")   # the curtain line follows it too
        eng.detach(self.ws)
        self.assertIsNone(eng.rooms_state)               # forgotten when the game leaves

    def test_caps(self):
        st = clean_rooms_state({"rooms": [["r", "R"]] * 500, "views": "nope", "screen": 3})
        self.assertEqual(len(st["rooms"]), 60)
        self.assertEqual(st["views"], [])
        self.assertEqual(st["screen"], {})

    def test_actions_check_their_values(self):
        self.assertTrue(ROOMS_ACTIONS["pause"]("toggle"))
        self.assertFalse(ROOMS_ACTIONS["pause"]("maybe"))
        self.assertTrue(ROOMS_ACTIONS["volume"](0.4))
        self.assertFalse(ROOMS_ACTIONS["volume"](3))
        self.assertFalse(ROOMS_ACTIONS["volume"](True))
        self.assertTrue(ROOMS_ACTIONS["presenter"]("2:on"))
        self.assertFalse(ROOMS_ACTIONS["presenter"]("9:on"))
        self.assertFalse(ROOMS_ACTIONS["room"](""))
        # Big screen picker: a source by name, a video link, Stop
        self.assertTrue(ROOMS_ACTIONS["spout"]("VTubeStudioSpout"))
        self.assertFalse(ROOMS_ACTIONS["spout"](""))
        self.assertFalse(ROOMS_ACTIONS["ndi"](5))
        self.assertTrue(ROOMS_ACTIONS["video"]("https://www.youtube.com/watch?v=x"))
        self.assertFalse(ROOMS_ACTIONS["video"]("   "))
        self.assertTrue(ROOMS_ACTIONS["stop"](""))

    def test_sources_are_cleaned(self):
        """The Big screen picker's lists: names only, capped; only the game's local sender page is linked."""
        st = clean_rooms_state({"sources": {"ndi": ["PC (OBS)", 7, "x" * 300] + ["n"] * 100, "spout": "nope",
                                            "sender_url": "http://127.0.0.1:8765/"}})
        self.assertEqual(st["sources"]["ndi"][0], "PC (OBS)")
        self.assertEqual(len(st["sources"]["ndi"]), 40)
        self.assertNotIn(7, st["sources"]["ndi"])
        self.assertEqual(st["sources"]["spout"], [])
        self.assertEqual(st["sources"]["sender_url"], "http://127.0.0.1:8765/")
        bad = clean_rooms_state({"sources": {"sender_url": "javascript:alert(1)"}})
        self.assertEqual(bad["sources"]["sender_url"], "")
        self.assertEqual(clean_rooms_state({})["sources"]["ndi"], [])

    def test_send_stage_carries_any_value(self):
        self.hello()
        self.assertTrue(run(self.h.eng.send_stage("volume", 0.25)))
        self.assertEqual(self.ws.sent[-1], {"type": "stage", "data": {"action": "volume", "value": 0.25}})


class RouteTests(unittest.TestCase):
    def test_routes(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.admin_routes import create_admin_router
        from api.server import CoreState

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        h = Harness(Path(tmp.name))
        disk = {"points": {"admin_token": TOKEN}}
        state = CoreState()
        state.config = json.loads(json.dumps(disk))
        state.reactions = h.eng
        app = FastAPI()
        app.include_router(create_admin_router(state))
        with mock.patch("api.admin_routes.load_config", lambda: json.loads(json.dumps(disk))):
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/admin/rooms").status_code, 401)
                self.assertEqual(client.get("/api/admin/rooms", headers=HEAD).json(), {"connected": False, "state": None})
                # no game: 409, a bad action: 400
                self.assertEqual(client.post("/api/admin/rooms", headers=HEAD, json={"action": "pause", "value": "on"}).status_code, 409)
                self.assertEqual(client.post("/api/admin/rooms", headers=HEAD, json={"action": "quit", "value": ""}).status_code, 400)
                ws = FakeWS()
                run(h.eng.on_client_message(ws, {"type": "hello", "data": {}}))
                run(h.eng.on_client_message(ws, {"type": "rooms_state", "data": STATE}))
                got = client.get("/api/admin/rooms", headers=HEAD).json()
                self.assertTrue(got["connected"])
                self.assertEqual(got["state"]["views"][0]["name"], "Wide")
                r = client.post("/api/admin/rooms", headers=HEAD, json={"action": "view", "value": "b0"})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(ws.sent[-1]["data"], {"action": "view", "value": "b0"})



class SettingsAndPrefsTests(unittest.TestCase):
    """Setup > Stream Rooms settings (rooms_settings / rooms_set), dashboard prefs and scenes."""

    SCHEMA = [{"key": "volume", "type": "range", "min": 0.0, "max": 1.0, "label": "Video volume", "tab": "Sound"},
              {"key": "crowd", "type": "bool", "label": "Filler crowd", "tab": "Audience"},
              {"key": "quality", "type": "choice", "options": [["low", "Low"], ["high", "High"]], "label": "Q", "tab": "Room"},
              {"key": "seats", "type": "range", "min": 0, "max": 50, "int": True, "label": "Seats", "tab": "Seating"},
              {"key": "tint", "type": "color", "label": "Tint", "tab": "Room"},
              {"key": "bad", "type": "nope"}]

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.admin_routes import create_admin_router
        from api.server import CoreState

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.h = Harness(Path(self.tmp.name))
        disk = {"points": {"admin_token": TOKEN}}
        state = CoreState()
        state.config = json.loads(json.dumps(disk))
        state.reactions = self.h.eng
        app = FastAPI()
        app.include_router(create_admin_router(state))
        p = mock.patch("api.admin_routes.load_config", lambda: json.loads(json.dumps(disk)))
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app)
        self.ws = FakeWS()
        run(self.h.eng.on_client_message(self.ws, {"type": "hello", "data": {}}))
        run(self.h.eng.on_client_message(self.ws, {"type": "rooms_settings", "data": {
            "schema": self.SCHEMA, "values": {"volume": 0.8, "crowd": True, "quality": "low", "seats": 10, "tint": "#ffffff", "other": 1},
            "defaults": {"volume": 0.8, "crowd": True}}}))

    def test_schema_kept_clean(self):
        got = self.client.get("/api/admin/rooms/settings", headers=HEAD).json()
        self.assertEqual([e["key"] for e in got["schema"]], ["volume", "crowd", "quality", "seats", "tint"])
        self.assertNotIn("other", got["values"])

    def test_set_checks_type_and_range(self):
        post = lambda k, v: self.client.post("/api/admin/rooms/set", headers=HEAD, json={"key": k, "value": v})
        self.assertEqual(post("volume", 0.5).status_code, 200)
        self.assertEqual(self.ws.sent[-1], {"type": "rooms_set", "data": {"key": "volume", "value": 0.5}})
        self.assertEqual(post("volume", 2).status_code, 400)
        self.assertEqual(post("crowd", "yes").status_code, 400)
        self.assertEqual(post("quality", "ultra").status_code, 400)
        self.assertEqual(post("quality", "high").status_code, 200)
        self.assertEqual(post("seats", 12.0).status_code, 200)
        self.assertEqual(self.ws.sent[-1]["data"]["value"], 12)          # an int setting stays an int
        self.assertEqual(post("tint", "red").status_code, 400)
        self.assertEqual(post("unknown", 1).status_code, 400)
        # the game's own change comes back as rooms_values
        run(self.h.eng.on_client_message(self.ws, {"type": "rooms_values", "data": {"volume": 0.3, "sneaky": 1}}))
        vals = self.client.get("/api/admin/rooms/settings", headers=HEAD).json()["values"]
        self.assertEqual(vals["volume"], 0.3)
        self.assertNotIn("sneaky", vals)

    def test_prefs_merge_and_scene(self):
        put = lambda body: self.client.put("/api/admin/dashboard-prefs", headers=HEAD, json=body).json()
        put({"live_layout": {"pc": {"order": ["a", "b"], "hidden": ["c"], "junk": 1}}})
        got = put({"live_layout": {"phone": {"order": ["b"]}}, "pins": [{"key": "volume", "label": "Vol"}, {"key": "volume"}]})
        self.assertEqual(got["live_layout"]["pc"]["order"], ["a", "b"])      # the PC's layout kept
        self.assertEqual(got["live_layout"]["phone"]["order"], ["b"])
        self.assertEqual(len(got["pins"]), 1)                                # no duplicate pins
        got = put({"scenes": [{"id": "s1", "name": "Intermission", "steps": [
            {"kind": "curtain", "value": "close"}, {"kind": "set", "key": "volume", "value": 0.2},
            {"kind": "cmd", "action": "focus", "value": "on"}, {"kind": "evil", "value": 1}]}]})
        self.assertEqual(len(got["scenes"][0]["steps"]), 3)                  # the unknown step dropped
        self.assertEqual(got["pins"][0]["key"], "volume")                    # pins kept by a scenes save
        r = self.client.post("/api/admin/rooms/scene", headers=HEAD, json={"id": "s1"}).json()
        self.assertTrue(r["ok"])
        kinds = [(m["type"], m["data"].get("action") or m["data"].get("key")) for m in self.ws.sent[-3:]]
        self.assertEqual(kinds, [("stage", "curtain"), ("rooms_set", "volume"), ("stage", "focus")])
        self.assertEqual(self.client.post("/api/admin/rooms/scene", headers=HEAD, json={"id": "nope"}).status_code, 404)
        # the file lives in the engine's data folder (a temp folder here)
        self.assertTrue((Path(self.tmp.name) / "dashboard_prefs.json").exists())


if __name__ == "__main__":
    unittest.main()
