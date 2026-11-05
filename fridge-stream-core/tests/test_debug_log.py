"""Troubleshooting log files: core/debug_log.py (the cleaner, the per-run file, the crash note)
and api/log_routes.py (list, download, name checks). Everything runs in a temporary folder, so
the real data/logs_to_share is never touched.

    python -m pytest tests/test_debug_log.py -q
"""

from __future__ import annotations

import copy
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import debug_log  # noqa: E402
from core.config import DEFAULTS  # noqa: E402

TOKEN = "tok-123456789abc"


class CleanerTests(unittest.TestCase):
    def setUp(self):
        env = {"USERNAME": "Jonathan", "COMPUTERNAME": "GAMING-RIG", "USERPROFILE": r"C:\Users\Jonathan"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.c = debug_log.Cleaner(Path(r"G:\AI\claude\FlaVR_leftovers\fridge-stream-core"),
                                   ["supersecretclientsecret", "abc"])

    def test_addresses_get_numbered_tags(self):
        self.assertEqual(self.c.clean("from 192.168.1.20 and 8.8.4.4"), "from <ip-home#1> and <ip#2>")
        self.assertEqual(self.c.clean("again 8.8.4.4, then 100.101.1.2"), "again <ip#2>, then <ip-tailscale#3>")

    def test_this_pc_times_and_versions_stay(self):
        for s in ("ws://127.0.0.1:3850/ws", "at 18:12:09 ok", "Redot 26.2.0.stable", "bind 0.0.0.0:3860"):
            self.assertEqual(self.c.clean(s), s)

    def test_ipv6(self):
        self.assertTrue(self.c.clean("peer fe80::1c2b:3d4e:5f60:7a8b%12 up").startswith("peer <ip6#"))
        self.assertEqual(self.c.clean("loopback ::1"), "loopback ::1")

    def test_folders_and_names(self):
        out = self.c.clean(r"File G:\AI\claude\FlaVR_leftovers\fridge-stream-core\core\tts.py, line 3")
        self.assertEqual(out, r"File <core folder>\core\tts.py, line 3")
        out = self.c.clean(r"C:\Users\Jonathan\Documents\clip.mp4 and C:\Users\Pat Smith\Desktop\x.png")
        self.assertNotIn("Jonathan", out)
        self.assertNotIn("Pat", out)
        self.assertNotIn("Smith", out)
        self.assertIn("<documents>", out)
        self.assertEqual(self.c.clean("hello jonathan on gaming-rig"), "hello <user> on <pc>")

    def test_secrets_links_tunnels_mail(self):
        out = self.c.clean("secret supersecretclientsecret, link https://x.test/?token=zzz&a=1 oauth:q1w2 "
                           "Bearer abc.def me@example.com wss://brave-lion.trycloudflare.com")
        for gone in ("supersecretclientsecret", "zzz", "q1w2", "abc.def", "me@example.com", "brave-lion"):
            self.assertNotIn(gone, out)
        self.assertIn("a=1", out)
        # a value too short to be a real secret doesn't eat ordinary words
        self.assertEqual(self.c.clean("abcdef"), "abcdef")

    def test_secrets_in_config(self):
        cfg = {"kick": {"client_secret": "kick-secret-xyz", "channel_slug": "sensoka"},
               "points": {"admin_token": TOKEN}, "tts": {"server": {"api_key": "sk-1234567"}}}
        found = debug_log.secrets_in(cfg)
        self.assertIn("kick-secret-xyz", found)
        self.assertIn(TOKEN, found)
        self.assertIn("sk-1234567", found)
        self.assertNotIn("sensoka", found)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = copy.deepcopy(DEFAULTS)
        self.cfg["points"]["admin_token"] = TOKEN
        self.cfg["kick"]["enabled"] = True
        # the root logger is shared with every other test: put it back afterwards
        root_log = logging.getLogger()
        self.addCleanup(setattr, root_log, "level", root_log.level)
        self.addCleanup(debug_log.stop)
        self.addCleanup(setattr, sys, "excepthook", sys.excepthook)
        import threading
        self.addCleanup(setattr, threading, "excepthook", threading.excepthook)

    def _text(self, path):
        for h in logging.getLogger().handlers:
            h.flush()
        return path.read_text(encoding="utf-8")

    def test_writes_a_cleaned_file(self):
        path = debug_log.start(self.cfg, self.root)
        self.assertIsNotNone(path)
        self.assertEqual(path.parent, self.root / "data" / "logs_to_share")
        lg = logging.getLogger("adapters.kick")
        lg.info("connected to 203.0.113.9 with %s", TOKEN)
        lg.debug("[Kick] %s: %s", "someone", "hello chat")
        lg.debug("reconnect in 5s")
        logging.getLogger("httpx").debug("HTTP noise")
        text = self._text(path)
        self.assertTrue(text.startswith("=== Stream Core log for troubleshooting ==="))
        self.assertIn("Chat:       kick", text)
        self.assertIn("connected to <ip#", text)
        self.assertNotIn("203.0.113.9", text)
        self.assertNotIn(TOKEN, text)
        self.assertIn("reconnect in 5s", text, "DEBUG lines go in the file")
        self.assertNotIn("hello chat", text, "per-message chat lines stay out")
        self.assertNotIn("HTTP noise", text, "library chatter stays out")

    def test_off_writes_nothing(self):
        self.cfg["core"]["log_files"] = False
        self.assertIsNone(debug_log.start(self.cfg, self.root))
        self.assertEqual(list((self.root / "data" / "logs_to_share").glob("*.log")), [])

    def test_crash_note_and_clean_close(self):
        data = self.root / "data"
        data.mkdir(parents=True)
        (data / ".core_running").write_text("x")
        (data / ".crash_trace.txt").write_text(r'Fatal Python error: x' "\n" r'  File "C:\Users\Jonathan\a.py", line 1')
        with mock.patch.dict(os.environ, {"USERNAME": "Jonathan"}):
            path = debug_log.start(self.cfg, self.root)
        text = self._text(path)
        self.assertIn("didn't close normally", text)
        self.assertIn("Fatal Python error", text)
        self.assertNotIn("Jonathan", text)
        debug_log.stop()
        self.assertFalse((data / ".core_running").exists(), "a normal close removes the marker")
        self.assertFalse((data / ".crash_trace.txt").exists())
        self.assertIn("Core closing normally", path.read_text(encoding="utf-8"))

    def test_old_files_are_pruned(self):
        folder = debug_log.folder(self.root)
        for i in range(20):
            (folder / f"stream_core_2020-01-{i + 1:02d}_00-00-00.log").write_text("old")
        debug_log.start(self.cfg, self.root)
        self.assertEqual(len(list(folder.glob("stream_core_*.log"))), debug_log.KEEP_FILES)


class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.log_routes import create_log_router
        from api.server import CoreState

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        cfg = copy.deepcopy(DEFAULTS)
        cfg["points"]["admin_token"] = TOKEN
        state = CoreState()
        state.config = cfg
        self.folder = debug_log.folder(self.root)
        (self.folder / "stream_core_2026-11-05_18-00-00.log").write_text("one")
        (self.folder / "stream_core_2026-11-05_19-00-00.log").write_text("two")
        (self.root / "data" / "secret.txt").write_text("nope")
        app = FastAPI()
        app.include_router(create_log_router(state, self.root))
        self.client = TestClient(app)
        self.h = {"X-Admin-Token": TOKEN}

    def test_needs_the_token(self):
        self.assertEqual(self.client.get("/api/admin/logs").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/logs/file?app=core&name=x").status_code, 401)

    def test_lists_newest_first(self):
        data = self.client.get("/api/admin/logs", headers=self.h).json()
        self.assertTrue(data["enabled"])
        self.assertEqual([f["name"] for f in data["core"]],
                         ["stream_core_2026-11-05_19-00-00.log", "stream_core_2026-11-05_18-00-00.log"])

    def test_download_and_name_checks(self):
        r = self.client.get("/api/admin/logs/file", params={"app": "core", "name": "stream_core_2026-11-05_19-00-00.log"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "two")
        for name in ("../secret.txt", "secret.txt", "stream_core_2026-11-05_19-00-00.log/../../secret.txt"):
            r = self.client.get("/api/admin/logs/file", params={"app": "core", "name": name}, headers=self.h)
            self.assertEqual(r.status_code, 400, name)
        # a Stream Rooms name asked for as Core's (and the other way round) is refused
        r = self.client.get("/api/admin/logs/file", params={"app": "rooms", "name": "stream_core_2026-11-05_19-00-00.log"}, headers=self.h)
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
