"""Phone remote: pairing and keys (core/phone_remote.py), the phone door's checks and its
allow-list (api/phone_server.py), and the dashboard routes (api/phone_admin_routes.py).

    python -m pytest tests/test_phone_remote.py -q
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import admin_routes  # noqa: E402
from api.highlight_routes import create_highlight_router  # noqa: E402
from api.phone_server import ALLOWED, allowed, create_phone_app  # noqa: E402
from api.server import CoreState  # noqa: E402
from core.config import DEFAULTS, _deep_merge  # noqa: E402
from core.highlights import HighlightBoard  # noqa: E402
from core.phone_remote import MAX_CODE_TRIES, MAX_TRIES, PhoneRemote, is_home_address  # noqa: E402
from core.red_flags import RedFlags  # noqa: E402
from core.store import Store  # noqa: E402

TOKEN = "tok-123456789abc"
HOME = ("192.168.1.50", 40000)


class PairingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.r = PhoneRemote(self.root)

    def test_off_by_default(self):
        self.assertFalse(self.r.settings["enabled"])
        self.assertTrue(self.r.settings["stop_on_exit"])

    def test_pair_with_code_saves_only_a_hash(self):
        p = self.r.start_pairing()
        res = self.r.pair(p["code"], "", "Sen's phone", "192.168.1.9")
        self.assertTrue(res["ok"])
        saved = self.r.path.read_text(encoding="utf-8")
        self.assertNotIn(res["key"], saved)
        self.assertIsNotNone(self.r.check_key(res["key"]))
        self.assertIsNone(self.r.check_key("nope"))
        self.assertEqual(self.r.public_list()[0]["name"], "Sen's phone")
        self.assertNotIn("key_hash", self.r.public_list()[0])

    def test_qr_token_works_and_code_is_single_use(self):
        p = self.r.start_pairing()
        self.assertTrue(self.r.pair("", p["token"], "A", "192.168.1.9")["ok"])
        self.assertFalse(self.r.pair(p["code"], "", "B", "192.168.1.9")["ok"])

    def test_code_expires(self):
        p = self.r.start_pairing()
        self.r._pairing["until"] = time.time() - 1
        self.assertFalse(self.r.pair(p["code"], "", "A", "192.168.1.9")["ok"])

    def test_wrong_codes_lock_the_address_then_drop_the_code(self):
        p = self.r.start_pairing()
        wrong = "000000" if p["code"] != "000000" else "111111"
        for _ in range(MAX_TRIES):
            self.r.pair(wrong, "", "x", "192.168.1.66")
        res = self.r.pair(p["code"], "", "x", "192.168.1.66")
        self.assertFalse(res["ok"])
        self.assertIn("wait", res)
        # other addresses keep guessing until the code is thrown away
        n = 0
        while self.r.pairing_open() and n < MAX_CODE_TRIES * 2:
            self.r.pair(wrong, "", "x", f"192.168.2.{n % 250}")
            n += 1
        self.assertFalse(self.r.pairing_open())

    def test_remove_stops_the_key(self):
        p = self.r.start_pairing()
        res = self.r.pair(p["code"], "", "A", "192.168.1.9")
        self.assertTrue(self.r.remove(res["id"]))
        self.assertIsNone(self.r.check_key(res["key"]))
        # and it stays removed after a reload
        self.assertIsNone(PhoneRemote(self.root).check_key(res["key"]))

    def test_home_addresses(self):
        for ip in ("192.168.1.2", "10.0.0.5", "172.20.1.1", "fe80::1"):
            self.assertTrue(is_home_address(ip), ip)
        for ip in ("8.8.8.8", "127.0.0.1", "0.0.0.0", "testclient", ""):
            self.assertFalse(is_home_address(ip), ip)

    def test_fixed_host_must_be_home(self):
        self.assertEqual(PhoneRemote(self.root, {"phone_remote": {"host": "8.8.8.8"}}).settings["host"], "")
        self.assertEqual(PhoneRemote(self.root, {"phone_remote": {"host": "192.168.1.7"}}).settings["host"], "192.168.1.7")


class AllowListTests(unittest.TestCase):
    def test_live_actions_allowed(self):
        for m, p in (("POST", "/stage"), ("POST", "/credits/play"), ("POST", "/highlight"),
                     ("POST", "/highlight/next"), ("GET", "/users"), ("POST", "/users/12/points"),
                     ("POST", "/red-flags/flag"), ("DELETE", "/red-flags/3")):
            self.assertTrue(allowed(m, p), (m, p))

    def test_setup_and_secrets_refused(self):
        for m, p in (("GET", "/config"), ("PUT", "/config"), ("POST", "/restart"), ("POST", "/chat/clear"),
                     ("GET", "/twitch/auth"), ("POST", "/kick/auth/start"), ("PUT", "/red-flags"),
                     ("GET", "/red-flags"), ("POST", "/media"), ("PUT", "/plugins/x/settings"),
                     ("POST", "/users/1/merge"), ("POST", "/credits/reset"), ("GET", "/chat/export"),
                     ("GET", "/phone-remote"), ("POST", "/phone-remote/pair"), ("PUT", "/highlight/settings"),
                     ("POST", "/stage/../config"), ("GET", "/users/1/../../config")):
            self.assertFalse(allowed(m, p), (m, p))

    def test_list_has_no_put(self):
        self.assertFalse([m for m, _ in ALLOWED if m == "PUT"])


class DoorTests(unittest.TestCase):
    """The phone app against a real (small) main app: admin calls are passed through in-process."""

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = Store(self.root / "core.db", {"enabled": True}, {"enabled": True})
        self.state = CoreState()
        self.state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}})
        self.state.store = self.store
        self.state.red_flags = RedFlags(self.store, {})

        async def hide(*a):
            return None

        self.state.red_flag_hide = hide
        self.board = HighlightBoard(self.state.config)
        self.state.highlights = self.board
        main = FastAPI()
        main.include_router(admin_routes.create_admin_router(self.state))
        main.include_router(create_highlight_router(self.state, self.root))
        self.remote = PhoneRemote(self.root)
        phone = create_phone_app(self.state, self.remote, main, self.root)
        self.home = TestClient(phone, client=HOME)
        self.outside = TestClient(phone, client=("8.8.4.4", 5000))
        p = self.remote.start_pairing()
        r = self.home.post("/phone/api/pair", json={"code": p["code"], "name": "Test phone"})
        self.assertEqual(r.status_code, 200, r.text)
        self.key = {"X-Phone-Key": r.json()["key"]}

    def test_outside_callers_refused(self):
        self.assertEqual(self.outside.get("/phone/").status_code, 403)
        self.assertEqual(self.outside.get("/phone/api/summary", headers=self.key).status_code, 403)

    def test_page_served(self):
        r = self.home.get("/phone/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Pair this phone", r.text)
        self.assertEqual(self.home.get("/phone/phone.js").status_code, 200)
        self.assertEqual(self.home.get("/phone/..%2Fmain.py").status_code, 404)

    def test_key_needed(self):
        self.assertEqual(self.home.get("/phone/api/summary").status_code, 401)
        self.assertEqual(self.home.get("/phone/api/summary", headers={"X-Phone-Key": "x"}).status_code, 401)
        self.assertEqual(self.home.get("/phone/api/summary", headers=self.key).status_code, 200)

    def test_admin_token_never_needed_or_shown(self):
        self.board.note_chat({"platform": "kick", "message_id": "m1", "message": "hey",
                              "user": {"id": "1", "username": "amy", "display_name": "Amy"}})
        r = self.home.post("/phone/api/admin/highlight", headers=self.key, json={"platform": "kick", "message_id": "m1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["on_screen"])
        self.assertNotIn(TOKEN, r.text)
        recent = self.home.get("/phone/api/admin/highlight/recent?after=0", headers=self.key).json()
        self.assertEqual(recent["items"][0]["message_id"], "m1")

    def test_setup_routes_refused_through_the_door(self):
        for m, p in (("GET", "config"), ("POST", "restart"), ("GET", "twitch/auth"), ("POST", "chat/clear"),
                     ("GET", "red-flags")):
            r = self.home.request(m, "/phone/api/admin/" + p, headers=self.key, json={})
            self.assertEqual(r.status_code, 403, (m, p, r.text))

    def test_points_and_red_flag_from_the_phone(self):
        # A chatter Core has seen (the store makes the user row the dashboard's People page lists)
        uid = self.store._get_or_create_user_sync("twitch", "77", "otter", "Otter")
        rows = self.home.get("/phone/api/admin/users?q=otter", headers=self.key).json()
        rows = rows.get("users", rows) if isinstance(rows, dict) else rows
        self.assertEqual(rows[0]["id"], uid)
        r = self.home.post(f"/phone/api/admin/users/{uid}/points", headers=self.key, json={"delta": 100, "reason": "phone"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.home.post("/phone/api/admin/red-flags/flag", headers=self.key,
                           json={"name": "otter", "platform": "twitch", "platform_user_id": "77"})
        self.assertEqual(r.status_code, 200, r.text)
        flagged = self.home.get("/phone/api/flagged", headers=self.key).json()["flagged"]
        self.assertEqual(flagged[0]["username"], "otter")
        self.assertNotIn("phrases", json.dumps(flagged))

    def test_removed_phone_stops(self):
        pid = self.remote.public_list()[0]["id"]
        self.remote.remove(pid)
        self.assertEqual(self.home.get("/phone/api/me", headers=self.key).status_code, 401)

    def test_pair_wrong_code(self):
        self.remote.start_pairing()
        r = self.home.post("/phone/api/pair", json={"code": "not-it", "name": "x"})
        self.assertEqual(r.status_code, 403)


class DashboardRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.phone_admin_routes import create_phone_admin_router

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = CoreState()
        self.state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}})
        self.state.phone_remote = PhoneRemote(self.root)

        class FakeServer:
            running = False
            error = ""

            async def start(self):
                self.running = True
                return True

            async def stop(self):
                self.running = False

            def url(self):
                return "http://192.168.1.50:3860/phone/"

            def status(self):
                return {"running": self.running, "url": self.url() if self.running else "", "error": ""}

        self.state.phone_server = FakeServer()
        app = FastAPI()
        app.include_router(create_phone_admin_router(self.state, self.root))
        self.client = TestClient(app)
        self.saved = []
        import api.phone_admin_routes as par
        orig = par.save_config
        par.save_config = lambda cfg: self.saved.append(json.loads(json.dumps(cfg)))
        self.addCleanup(setattr, par, "save_config", orig)
        self.h = {"X-Admin-Token": TOKEN}

    def test_needs_admin_token(self):
        self.assertEqual(self.client.get("/api/admin/phone-remote").status_code, 401)

    def test_switch_on_pair_and_off(self):
        self.assertEqual(self.client.post("/api/admin/phone-remote/pair", headers=self.h).status_code, 409)
        r = self.client.put("/api/admin/phone-remote/enabled", headers=self.h, json={"enabled": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.saved[-1]["phone_remote"]["enabled"])
        p = self.client.post("/api/admin/phone-remote/pair", headers=self.h).json()
        self.assertRegex(p["code"], r"^\d{6}$")
        self.assertIn("#pair=" + p["token"], p["qr_url"])
        info = self.client.get("/api/admin/phone-remote", headers=self.h).json()
        self.assertTrue(info["pairing_open"])
        self.client.put("/api/admin/phone-remote/enabled", headers=self.h, json={"enabled": False})
        self.assertFalse(self.saved[-1]["phone_remote"]["enabled"])
        self.assertFalse(self.state.phone_remote.pairing_open())
        self.assertIn("points", self.saved[-1])   # other blocks kept

    def test_host_must_be_home(self):
        r = self.client.put("/api/admin/phone-remote/settings", headers=self.h, json={"host": "8.8.8.8"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
