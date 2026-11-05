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


if __name__ == "__main__":
    unittest.main()
