"""Only games may act as a game: no web pages, and other devices need the admin token.

The game WebSocket `hello` (then say / refund / room_state) and the market
signal / dividend POSTs can spend and mint points, so any web page open in the
streamer's browser (which passes the loopback-origin rule) is refused.

    python -m pytest tests/test_game_link_guard.py -q
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.local_guard import game_caller_problem, is_browser_request, is_loopback_client  # noqa: E402

TOKEN = "tok-game-123456789"
LOCAL = ("127.0.0.1", 50000)
LAN_PC = ("192.168.1.20", 50000)
PAGE = {"origin": "http://127.0.0.1:3850", "host": "127.0.0.1:3850"}


class FakeReactions:
    """Stands in for the reactions engine: answers hello like the real one."""

    def __init__(self):
        self.seen = []

    async def on_client_message(self, ws, msg):
        self.seen.append(msg.get("type"))
        if msg.get("type") == "hello":
            await ws.send_json({"type": "hello_ok", "data": {}})

    def detach(self, ws):
        pass


def make_state(lan: bool = False):
    from api.server import CoreState
    from core.market import MarketTape

    state = CoreState()
    state.config = {"points": {"admin_token": TOKEN}}
    if lan:
        state.config["core"] = {"host": "0.0.0.0"}
    state.reactions = FakeReactions()
    state.market = MarketTape({})
    state.hidden = []

    async def importer(names):
        state.hidden.extend(names)

    state.import_avatar_hide = importer
    return state


def client_for(state, client=LOCAL):
    from fastapi.testclient import TestClient

    from api.server import create_app

    return TestClient(create_app(state), base_url="http://127.0.0.1:3850", client=client)


def hello_answer(client, url="/ws", headers=None, data=None):
    with client.websocket_connect(url, headers=headers or {"host": "127.0.0.1:3850"}) as ws:
        ws.send_json({"type": "hello", "data": data or {"client": "stream_rooms", "protocol": 1}})
        while True:
            t = ws.receive_json().get("type")
            if t in ("hello_ok", "hello_refused"):
                return t


class RuleTests(unittest.TestCase):
    def test_browser_detection(self):
        self.assertTrue(is_browser_request({"origin": "http://localhost:5173"}))
        self.assertTrue(is_browser_request({"origin": "null"}))
        self.assertTrue(is_browser_request({"sec-fetch-site": "same-origin"}))
        # Node fetch sends sec-fetch-mode but no Origin / Sec-Fetch-Site
        self.assertFalse(is_browser_request({"sec-fetch-mode": "cors", "user-agent": "node"}))
        self.assertFalse(is_browser_request({}))

    def test_loopback_clients(self):
        for h in ("127.0.0.1", "127.0.0.5", "::1", "[::1]", "::ffff:127.0.0.1", "localhost"):
            self.assertTrue(is_loopback_client(h), h)
        for h in ("192.168.1.20", "10.0.0.2", "", None, "testclient"):
            self.assertFalse(is_loopback_client(h), h)

    def test_token_only_looked_up_for_other_devices(self):
        def boom():
            raise AssertionError("token looked up for a local game")

        self.assertIsNone(game_caller_problem({}, "127.0.0.1", None, boom))
        self.assertIsNotNone(game_caller_problem({}, "192.168.1.20", None, lambda: TOKEN))
        self.assertIsNone(game_caller_problem({}, "192.168.1.20", TOKEN, lambda: TOKEN))
        # a web page never gets in, token or not
        self.assertIsNotNone(game_caller_problem(PAGE, "127.0.0.1", TOKEN, lambda: TOKEN))


class WebSocketTests(unittest.TestCase):
    def test_game_on_same_pc_says_hello(self):
        state = make_state()
        with client_for(state) as c:
            self.assertEqual(hello_answer(c), "hello_ok")
        self.assertEqual(state.reactions.seen, ["hello"])

    def test_web_page_hello_refused(self):
        state = make_state()
        with client_for(state) as c:
            self.assertEqual(hello_answer(c, headers=PAGE), "hello_refused")
            # the root socket path too, and a token doesn't help a web page
            self.assertEqual(hello_answer(c, url="/?token=" + TOKEN, headers=PAGE), "hello_refused")
        self.assertEqual(state.reactions.seen, [])

    def test_refused_page_cannot_use_game_messages(self):
        state = make_state()
        with client_for(state) as c:
            with c.websocket_connect("/ws", headers=PAGE) as ws:
                ws.send_json({"type": "hello", "data": {}})
                ws.send_json({"type": "say", "data": {"text": "free points"}})
                ws.send_json({"type": "avatars_hide_import", "data": {"names": ["streamer"]}})
                ws.send_text("ping")
                types = []
                while "pong" not in types:
                    types.append(ws.receive_json().get("type"))
        self.assertEqual(types.count("hello_refused"), 2)
        # "say" reaches the engine, which ignores it from a socket that never said hello
        self.assertEqual(state.reactions.seen, ["say"])
        self.assertEqual(state.hidden, [])

    def test_hide_list_from_stream_rooms_still_works(self):
        state = make_state()
        with client_for(state) as c:
            with c.websocket_connect("/ws", headers={"host": "127.0.0.1:3850"}) as ws:
                ws.send_json({"type": "avatars_hide_import", "data": {"names": ["bot"]}})
                ws.send_text("ping")
                while ws.receive_json().get("type") != "pong":
                    pass
        self.assertEqual(state.hidden, ["bot"])

    def test_other_device_needs_token(self):
        state = make_state(lan=True)
        with client_for(state, client=LAN_PC) as c:
            self.assertEqual(hello_answer(c), "hello_refused")
            self.assertEqual(hello_answer(c, url="/ws?token=wrong"), "hello_refused")
            self.assertEqual(hello_answer(c, url="/ws?token=" + TOKEN), "hello_ok")
            self.assertEqual(hello_answer(c, data={"client": "game", "token": TOKEN}), "hello_ok")


class MarketPostTests(unittest.TestCase):
    BODY = {"game": "factorio", "symbol": "PWR", "work": 100, "unit": "mj"}

    def test_bridge_on_same_pc_allowed(self):
        state = make_state()
        with client_for(state) as c:
            r = c.post("/api/market/dividend", json=self.BODY,
                       headers={"sec-fetch-mode": "cors", "user-agent": "node"})
            self.assertEqual(r.status_code, 200, r.text)
            r = c.post("/api/market/signal", json={"name": "player_death", "symbol": "FRG"})
            self.assertEqual(r.status_code, 200, r.text)

    def test_web_page_refused(self):
        state = make_state()
        with client_for(state) as c:
            for path, body in (("/api/market/dividend", self.BODY),
                               ("/api/market/signal", {"name": "boom", "symbol": "FRG", "pct": 50})):
                r = c.post(path, json=body, headers=PAGE)
                self.assertEqual(r.status_code, 403, path)
                r = c.post(path, json=body, headers={"sec-fetch-site": "same-origin", "x-admin-token": TOKEN})
                self.assertEqual(r.status_code, 403, path)
        self.assertIsNone(getattr(state.market, "last_dividend", None))

    def test_other_device_needs_token(self):
        state = make_state(lan=True)
        with client_for(state, client=LAN_PC) as c:
            self.assertEqual(c.post("/api/market/dividend", json=self.BODY).status_code, 403)
            r = c.post("/api/market/dividend", json=self.BODY, headers={"X-Admin-Token": TOKEN})
            self.assertEqual(r.status_code, 200, r.text)
            r = c.post("/api/market/signal?token=" + TOKEN, json={"name": "x", "symbol": "FRG"})
            self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
