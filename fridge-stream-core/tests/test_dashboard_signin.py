"""Easier dashboard sign-in (core/dashboard_signin.py, checklists/admin-hub.md):
the shortcut beside START Stream Core.bat, opening the dashboard until it has signed in once,
and the "Sign in on this PC" route that only Core's own page on Core's own PC may use.

    python -m pytest tests/test_dashboard_signin.py -q
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from api import admin_routes  # noqa: E402
from api.server import CoreState  # noqa: E402
from core import dashboard_signin  # noqa: E402
from core.config import DEFAULTS, _deep_merge  # noqa: E402

TOKEN = "tok-123456789abc"
OWN = {"host": "127.0.0.1:3850", "origin": "http://127.0.0.1:3850", "sec-fetch-site": "same-origin"}


class ShortcutTests(unittest.TestCase):
    def test_workshop_folder_gets_its_own_shortcut(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Path(tmp) / "fridge-stream-core"
            core.mkdir()
            (Path(tmp) / "START Stream Core.bat").write_text("@echo off\r\n")
            with mock.patch.object(main, "ROOT", core):
                link = main.announce_dashboard(_deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}}), "127.0.0.1", 3850)
            for path in (core / "data" / "Open dashboard.url", Path(tmp) / "Open Stream Core dashboard.url"):
                self.assertIn(f"URL={link}", path.read_text(encoding="utf-8"))

    def test_no_shortcut_outside_a_workshop_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Path(tmp) / "fridge-stream-core"
            written = dashboard_signin.write_shortcuts(core, "http://127.0.0.1:3850/admin/#token=x")
            self.assertEqual(written, [core / "data" / "Open dashboard.url"])
            self.assertFalse((Path(tmp) / "Open Stream Core dashboard.url").exists())

    def test_shortcut_name_is_git_ignored(self):
        ignore = (ROOT.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(dashboard_signin.WORKSHOP_SHORTCUT, ignore)


class OpenAtStartTests(unittest.TestCase):
    def setUp(self):
        self._was = dashboard_signin._marked
        dashboard_signin._marked = False

    def tearDown(self):
        dashboard_signin._marked = self._was

    def test_opens_until_signed_in_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            off = {"core": {"open_dashboard": False}}
            self.assertTrue(dashboard_signin.should_open_at_start(off, root))
            dashboard_signin.mark_signed_in(root)
            self.assertTrue((root / "data" / "dashboard_signed_in").exists())
            self.assertFalse(dashboard_signin.should_open_at_start(off, root))
            self.assertTrue(dashboard_signin.should_open_at_start({"core": {"open_dashboard": True}}, root))

    def test_good_token_marks_signed_in_bad_one_does_not(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(admin_routes, "_CORE_ROOT", Path(tmp)):
            state = CoreState()
            state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}})
            app = FastAPI()
            app.include_router(admin_routes.create_admin_router(state))
            client = TestClient(app)
            marker = Path(tmp) / "data" / "dashboard_signed_in"
            client.get("/api/admin/activity", headers={"X-Admin-Token": "wrong"})
            self.assertFalse(marker.exists())
            client.get("/api/admin/activity", headers={"X-Admin-Token": TOKEN})
            self.assertTrue(marker.exists())


class SignInHereTests(unittest.TestCase):
    def test_rules(self):
        ok = dashboard_signin.sign_in_here_problem
        self.assertIsNone(ok("127.0.0.1", OWN))
        self.assertIsNone(ok("::1", {**OWN, "sec-fetch-site": ""}))
        # another PC, even with the right headers
        self.assertIsNotNone(ok("192.168.1.20", OWN))
        # no Origin (a script, not a page) or another loopback app's page (CORS would let it read)
        self.assertIsNotNone(ok("127.0.0.1", {**OWN, "origin": ""}))
        self.assertIsNotNone(ok("127.0.0.1", {**OWN, "origin": "http://127.0.0.1:3854"}))
        self.assertIsNotNone(ok("127.0.0.1", {**OWN, "origin": "http://evil.example"}))
        self.assertIsNotNone(ok("127.0.0.1", {**OWN, "sec-fetch-site": "same-site"}))
        # a LAN Host header (only when someone runs Core on a LAN address on purpose)
        lan = {"host": "192.168.1.5:3850", "origin": "http://192.168.1.5:3850"}
        self.assertIsNotNone(ok("127.0.0.1", lan))

    def _client(self, host):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        state = CoreState()
        state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}})
        app = FastAPI()
        app.include_router(admin_routes.create_admin_router(state))
        return TestClient(app, base_url="http://127.0.0.1:3850", client=(host, 50000))

    def test_route_gives_token_to_own_page_only(self):
        res = self._client("127.0.0.1").post("/api/admin/sign-in-here", headers={"Origin": OWN["origin"]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"token": TOKEN})
        res = self._client("127.0.0.1").post("/api/admin/sign-in-here", headers={"Origin": "http://127.0.0.1:3854"})
        self.assertEqual(res.status_code, 403)
        self.assertNotIn(TOKEN, res.text)
        res = self._client("10.0.0.7").post("/api/admin/sign-in-here", headers={"Origin": OWN["origin"]})
        self.assertEqual(res.status_code, 403)

    def test_phone_door_never_passes_it_on(self):
        from api import phone_server

        self.assertFalse(phone_server.allowed("POST", "/sign-in-here"))
        self.assertFalse(phone_server.allowed("POST", "/api/admin/sign-in-here"))


if __name__ == "__main__":
    unittest.main()
