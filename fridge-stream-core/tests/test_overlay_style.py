"""Overlay looks: the chat overlay's skin / CSS / options, pictures and sounds for chat and alerts,
and the dashboard endpoints behind them. Run from fridge-stream-core:

    python -m unittest tests.test_overlay_style -v
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import alerts  # noqa: E402
from core.chat_style import CHAT_STYLE, IMAGE_SLOTS, SOUND_SLOTS  # noqa: E402
from core.overlay_style import OverlayStyle, sniff  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 20
GIF = b"GIF89a" + b"\0" * 20
WEBM = b"\x1a\x45\xdf\xa3" + b"\0" * 20
MP3 = b"ID3" + b"\0" * 20
OGG = b"OggS" + b"\0" * 20
WAV = b"RIFF" + b"\0\0\0\0" + b"WAVE" + b"\0" * 12
WEBP = b"RIFF" + b"\0\0\0\0" + b"WEBP" + b"\0" * 12


class SniffTests(unittest.TestCase):
    def test_types(self):
        self.assertEqual(sniff(PNG), "png")
        self.assertEqual(sniff(GIF), "gif")
        self.assertEqual(sniff(WEBM), "webm")
        self.assertEqual(sniff(MP3), "mp3")
        self.assertEqual(sniff(b"\xff\xfb" + b"\0" * 10), "mp3")
        self.assertEqual(sniff(OGG), "ogg")
        self.assertEqual(sniff(WAV), "wav")
        self.assertEqual(sniff(WEBP), "webp")
        self.assertIsNone(sniff(b"<svg></svg>"))
        self.assertIsNone(sniff(b""))


class ChatStyleTests(unittest.TestCase):
    def test_defaults_and_options(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            s = CHAT_STYLE.read_settings(overlay_dir=root)
            self.assertEqual(s["skin"], "classic")
            self.assertEqual(s["css_version"], 0)
            self.assertEqual(s["options"]["max_messages"], 30)
            self.assertEqual(s["media"], {})
            self.assertEqual(s["sounds"], {})
            # options are typed, clamped and unknown keys dropped
            s = CHAT_STYLE.write_settings(options={"hide_after_sec": "15", "max_messages": 9999, "newest_on_top": "true",
                                                   "sound_volume": 3, "bogus": 1}, overlay_dir=root)
            self.assertEqual(s["options"]["hide_after_sec"], 15)
            self.assertEqual(s["options"]["max_messages"], 200)
            self.assertTrue(s["options"]["newest_on_top"])
            self.assertEqual(s["options"]["sound_volume"], 1.0)
            self.assertNotIn("bogus", s["options"])
            self.assertTrue(s["options"]["show_avatars"])            # untouched ones keep their default
            s = CHAT_STYLE.write_settings(skin="plain", overlay_dir=root)
            self.assertEqual(s["skin"], "plain")
            self.assertEqual(s["options"]["hide_after_sec"], 15)       # a skin change keeps the options
            self.assertEqual(CHAT_STYLE.write_settings(skin="nope", overlay_dir=root)["skin"], "plain")

    def test_custom_css(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            s = CHAT_STYLE.write_css(".name { color: red; }\r\n", overlay_dir=root)
            self.assertGreater(s["css_version"], 0)
            self.assertEqual(CHAT_STYLE.read_css(overlay_dir=root), ".name { color: red; }\n")
            with self.assertRaises(ValueError):
                CHAT_STYLE.write_css("<script>alert(1)</script>", overlay_dir=root)
            with self.assertRaises(ValueError):
                CHAT_STYLE.write_css("x" * 300_000, overlay_dir=root)

    def test_assets_upload_list_delete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            url = CHAT_STYLE.save_asset("badge-mod", PNG, overlay_dir=root)
            self.assertEqual(url, "assets/chat/badge-mod.png")
            # a data: URL upload of another format replaces the old file
            b64 = "data:image/gif;base64," + base64.b64encode(GIF).decode()
            self.assertEqual(CHAT_STYLE.save_asset_base64("badge-mod", b64, overlay_dir=root), "assets/chat/badge-mod.gif")
            self.assertFalse((root / "assets" / "chat" / "badge-mod.png").exists())
            CHAT_STYLE.save_asset("background", WEBP, overlay_dir=root)
            CHAT_STYLE.save_asset("message", MP3, overlay_dir=root)
            CHAT_STYLE.save_asset("paid", OGG, overlay_dir=root)
            media, sounds = CHAT_STYLE.list_assets(overlay_dir=root)
            self.assertEqual(media, {"badge-mod": "assets/chat/badge-mod.gif", "background": "assets/chat/background.webp"})
            self.assertEqual(sounds, {"message": "assets/chat/message.mp3", "paid": "assets/chat/paid.ogg"})
            s = CHAT_STYLE.read_settings(overlay_dir=root)
            self.assertEqual(s["sounds"]["paid"], "assets/chat/paid.ogg")
            # wrong kind of file for the slot, unknown slot, empty, too big
            with self.assertRaises(ValueError):
                CHAT_STYLE.save_asset("message", PNG, overlay_dir=root)
            with self.assertRaises(ValueError):
                CHAT_STYLE.save_asset("badge-vip", MP3, overlay_dir=root)
            with self.assertRaises(ValueError):
                CHAT_STYLE.save_asset("nope", PNG, overlay_dir=root)
            with self.assertRaises(ValueError):
                CHAT_STYLE.save_asset("background", b"", overlay_dir=root)
            with self.assertRaises(ValueError):
                CHAT_STYLE.save_asset("background", b"<svg onload=alert(1)>", overlay_dir=root)
            self.assertTrue(CHAT_STYLE.delete_asset("badge-mod", overlay_dir=root))
            self.assertFalse(CHAT_STYLE.delete_asset("badge-mod", overlay_dir=root))
            self.assertNotIn("badge-mod", CHAT_STYLE.list_assets(overlay_dir=root)[0])

    def test_slots_are_what_the_page_expects(self):
        self.assertIn("background", IMAGE_SLOTS)
        for k in ("broadcaster", "mod", "vip", "sub", "og", "founder"):
            self.assertIn(f"badge-{k}", IMAGE_SLOTS)
        self.assertEqual(SOUND_SLOTS, ("message", "paid"))


class AlertStyleTests(unittest.TestCase):
    """The alerts overlay kept its helper functions; sounds and a volume option were added."""

    def test_alert_helpers_still_work(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            alerts.write_custom_css(".name { color: red; }\n", overlay_dir=root)
            s = alerts.read_alert_settings(overlay_dir=root)
            self.assertGreater(s["css_version"], 0)
            self.assertEqual(s["skin"], "classic")
            self.assertEqual(s["options"]["sound_volume"], 0.8)
            alerts.write_alert_settings(skin="custom", overlay_dir=root)
            self.assertEqual(alerts.read_alert_settings(overlay_dir=root)["skin"], "custom")
            alerts.write_alert_settings(options={"sound_volume": 0.25}, overlay_dir=root)
            self.assertEqual(alerts.read_alert_settings(overlay_dir=root)["options"]["sound_volume"], 0.25)
            (root / "assets" / "alerts").mkdir(parents=True)
            (root / "assets" / "alerts" / "follow.gif").write_bytes(GIF)
            (root / "assets" / "alerts" / "follow.webm").write_bytes(WEBM)
            (root / "assets" / "alerts" / "raid.mp3").write_bytes(MP3)
            self.assertEqual(alerts.list_alert_media(overlay_dir=root)["follow"], "assets/alerts/follow.webm")  # WebM first
            self.assertEqual(alerts.read_alert_settings(overlay_dir=root)["sounds"], {"raid": "assets/alerts/raid.mp3"})
            self.assertEqual(alerts.ALERT_STYLE.save_asset("subscribe", WAV, overlay_dir=root), "assets/alerts/subscribe.wav")
            self.assertEqual(alerts.ALERT_STYLE.save_asset("subscribe", PNG, overlay_dir=root), "assets/alerts/subscribe.png")
            media, sounds = alerts.ALERT_STYLE.list_assets(overlay_dir=root)
            self.assertEqual(media["subscribe"], "assets/alerts/subscribe.png")   # picture and sound live side by side
            self.assertEqual(sounds["subscribe"], "assets/alerts/subscribe.wav")
            self.assertTrue(alerts.ALERT_STYLE.delete_asset("subscribe", kind="sound", overlay_dir=root))
            media, sounds = alerts.ALERT_STYLE.list_assets(overlay_dir=root)
            self.assertIn("subscribe", media)
            self.assertNotIn("subscribe", sounds)
            with self.assertRaises(ValueError):
                alerts.write_custom_css("<script>alert(1)</script>", overlay_dir=root)


class AdminRouteTests(unittest.TestCase):
    TOKEN = "unit-test-admin-token-123456"

    def test_chat_style_and_assets_endpoints(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.admin_routes import create_admin_router
        from api.server import CoreState

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            style = OverlayStyle("chat", CHAT_STYLE.skins, CHAT_STYLE.image_slots, CHAT_STYLE.sound_slots,
                                 CHAT_STYLE.default_options, CHAT_STYLE.ranges, overlay_dir=root)
            import core.chat_style as cs
            saved = cs.CHAT_STYLE
            cs.CHAT_STYLE = style
            try:
                state = CoreState()
                state.config = {"points": {"admin_token": self.TOKEN}}
                app = FastAPI()
                app.include_router(create_admin_router(state))
                hdr = {"X-Admin-Token": self.TOKEN}
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/admin/chat/style").status_code, 401)
                    st = client.get("/api/admin/chat/style", headers=hdr).json()
                    self.assertEqual(st["skin"], "classic")
                    self.assertEqual(st["skins"], ["classic", "plain", "custom"])
                    res = client.put("/api/admin/chat/style", headers=hdr,
                                     json={"skin": "plain", "css": ".msg { font-size: 20px; }", "options": {"hide_after_sec": 8}}).json()
                    self.assertTrue(res["ok"])
                    self.assertEqual(res["skin"], "plain")
                    self.assertEqual(res["options"]["hide_after_sec"], 8)
                    st = client.get("/api/admin/chat/style", headers=hdr).json()
                    self.assertEqual(st["css"], ".msg { font-size: 20px; }")
                    self.assertEqual(client.put("/api/admin/chat/style", headers=hdr, json={"skin": "neon"}).status_code, 400)
                    self.assertEqual(client.put("/api/admin/chat/style", headers=hdr,
                                                json={"css": "<script>x</script>"}).status_code, 400)
                    # pictures and sounds
                    lst = client.get("/api/admin/overlays/chat/assets", headers=hdr).json()
                    self.assertEqual(lst["sound_slots"], ["message", "paid"])
                    self.assertEqual(lst["media"], {})
                    up = client.post("/api/admin/overlays/chat/assets/message", headers=hdr,
                                     json={"data": "data:audio/mpeg;base64," + base64.b64encode(MP3).decode()}).json()
                    self.assertEqual(up["url"], "assets/chat/message.mp3")
                    self.assertEqual(up["sounds"]["message"], "assets/chat/message.mp3")
                    bad = client.post("/api/admin/overlays/chat/assets/message", headers=hdr,
                                      json={"data": base64.b64encode(PNG).decode()})
                    self.assertEqual(bad.status_code, 400)
                    self.assertEqual(client.post("/api/admin/overlays/chat/assets/nope", headers=hdr,
                                                 json={"data": base64.b64encode(PNG).decode()}).status_code, 400)
                    self.assertEqual(client.get("/api/admin/overlays/other/assets", headers=hdr).status_code, 404)
                    rm = client.delete("/api/admin/overlays/chat/assets/message", headers=hdr).json()
                    self.assertEqual(rm["sounds"], {})
                    self.assertEqual(client.delete("/api/admin/overlays/chat/assets/message", headers=hdr).status_code, 404)
                    # the settings json never carries anything but skin / version / options
                    data = json.loads((root / "chat-settings.json").read_text(encoding="utf-8"))
                    self.assertEqual(set(data), {"skin", "css_version", "options"})
            finally:
                cs.CHAT_STYLE = saved


if __name__ == "__main__":
    unittest.main()
