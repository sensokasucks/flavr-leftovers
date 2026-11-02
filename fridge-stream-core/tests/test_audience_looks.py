"""Audience looks (core/audience_looks.py): Stream Rooms' bubble and silhouette looks kept by Core,
the dashboard routes, the /ws message, and stored pictures following Rename / Delete.

    python -m pytest tests/test_audience_looks.py -q
"""

from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import admin_routes  # noqa: E402
from api.server import CoreState  # noqa: E402
from core.audience_looks import AudienceLooks, normalize  # noqa: E402
from core.media_library import MediaLibrary  # noqa: E402

TOKEN = "tok-123456789abc"
HEAD = {"X-Admin-Token": TOKEN}
# a 1x1 transparent PNG
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class NormalizeTests(unittest.TestCase):
    def test_keeps_known_keys_and_drops_the_rest(self):
        looks = normalize({"bubble_theme": "custom", "bubble": {"shape": 4, "fill": "ffffffff", "evil": "<script>"},
                           "silhouette": {"shape": "bot", "size": 1.2, "nested": {"x": 1}},
                           "saved": {"bubble": {"My|look": {"outline": 3}}},
                           "groups": {"mod": {"silhouette": "ears|bot"}, "nobody": {"bubble": "Comic"}}})
        self.assertEqual(looks["bubble_theme"], "custom")
        self.assertEqual(looks["bubble"], {"shape": 4, "fill": "ffffffff"})
        self.assertEqual(looks["silhouette"], {"shape": "bot", "size": 1.2})
        self.assertIn("My look", looks["saved"]["bubble"])         # the mix separator can't be in a name
        self.assertEqual(looks["groups"], {"mod": {"silhouette": "ears|bot"}})

    def test_unknown_theme_is_light(self):
        self.assertEqual(normalize({"bubble_theme": "rainbow"})["bubble_theme"], "light")
        self.assertEqual(normalize(None)["bubble_theme"], "light")


class StoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.media = MediaLibrary(self.root / "media")
        self.media.save(PNG, "cat")
        self.looks = AudienceLooks(self.root / "looks.json", media=lambda: self.media)
        self.sent: list = []
        self.looks.on_change = self.sent.append

    def test_save_sends_and_adds_picture_urls(self):
        self.assertFalse(self.looks.payload()["edited"])      # never saved: Stream Rooms leaves its looks alone
        self.looks.save({"silhouette": {"shape": "custom", "file": "media:cat"}})
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0]["edited"])
        pics = self.sent[0]["pictures"]
        self.assertIn("cat", pics)
        self.assertTrue(pics["cat"]["url"].startswith("/media/cat.png"))
        self.assertEqual(self.looks.load()["silhouette"]["file"], "media:cat")

    def test_missing_picture_has_no_url(self):
        payload = self.looks.save({"silhouette": {"shape": "custom", "file": "media:gone"}})
        self.assertEqual(payload["pictures"], {})

    def test_rename_and_delete_follow(self):
        self.looks.save({"silhouette": {"shape": "custom", "file": "media:cat"},
                         "saved": {"silhouette": {"Cat": {"shape": "custom", "file": "media:cat"}}}})
        refs = self.looks.media_refs()
        self.assertEqual({r["slot"] for r in refs}, {"Main silhouette", "Cat"})
        self.assertEqual(self.looks.media_renamed("cat", "kitty"), 2)
        self.assertEqual(self.looks.load()["silhouette"]["file"], "media:kitty")
        self.assertEqual(self.looks.media_forgotten("kitty"), 2)
        main = self.looks.load()["silhouette"]
        self.assertEqual(main["shape"], "classic")
        self.assertNotIn("file", main)

    def test_too_big_is_refused(self):
        # 200 presets with every text key filled to 200 characters is about 650 KB, over the 512 KB limit
        style = {k: "x" * 200 for k in ("fill", "text", "name_mode", "name_color", "outline_mode",
                                         "outline_color", "tail", "paid", "highlighted", "shape",
                                         "fill_mix", "outline", "text_size", "bold", "roundness", "width")}
        many = {f"look {i}": dict(style) for i in range(200)}
        with self.assertRaises(ValueError):
            self.looks.save({"saved": {"bubble": many}})


class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.state = CoreState()
        self.state.config = {"points": {"admin_token": TOKEN}}
        self.state.media = MediaLibrary(root / "media")
        self.state.media.save(PNG, "cat")
        self.state.audience_looks = AudienceLooks(root / "looks.json", media=lambda: self.state.media)
        self.sent: list = []
        self.state.audience_looks.on_change = self.sent.append
        app = FastAPI()
        app.include_router(admin_routes.create_admin_router(self.state))
        self.client = TestClient(app)

    def test_get_put_and_stored_files_used_by(self):
        self.assertEqual(self.client.get("/api/admin/audience-looks").status_code, 401)
        got = self.client.get("/api/admin/audience-looks", headers=HEAD).json()
        self.assertEqual(got["bubble_theme"], "light")
        r = self.client.put("/api/admin/audience-looks", headers=HEAD,
                            json={"bubble_theme": "dark", "silhouette": {"shape": "custom", "file": "media:cat"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["bubble_theme"], "dark")
        self.assertEqual(len(self.sent), 1)
        files = {f["name"]: f for f in self.client.get("/api/admin/media", headers=HEAD).json()["files"]}
        self.assertIn({"overlay": "audience looks", "slot": "Main silhouette", "kind": "image"}, files["cat"]["used_by"])
        # deleting the stored picture puts the classic silhouette back
        self.client.delete("/api/admin/media/cat", headers=HEAD)
        self.assertEqual(self.state.audience_looks.load()["silhouette"]["shape"], "classic")


if __name__ == "__main__":
    unittest.main()
