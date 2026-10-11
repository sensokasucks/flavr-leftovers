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
from core.media_library import MediaLibrary  # noqa: E402
from core.overlay_style import OverlayStyle, sniff  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 20
GIF = b"GIF89a" + b"\0" * 20
WEBM = b"\x1a\x45\xdf\xa3" + b"\0" * 20
MP3 = b"ID3" + b"\0" * 20
OGG = b"OggS" + b"\0" * 20
WAV = b"RIFF" + b"\0\0\0\0" + b"WAVE" + b"\0" * 12
WEBP = b"RIFF" + b"\0\0\0\0" + b"WEBP" + b"\0" * 12
MP4 = b"\0\0\0\x20ftypisom" + b"\0" * 20
M4A = b"\0\0\0\x20ftypM4A " + b"\0" * 20


def chat_style(root: Path) -> OverlayStyle:
    """The chat overlay's slots with its own folder and stored-files library (never the real ones)."""
    return OverlayStyle("chat", CHAT_STYLE.skins, CHAT_STYLE.image_slots, CHAT_STYLE.sound_slots,
                        CHAT_STYLE.default_options, CHAT_STYLE.ranges, overlay_dir=root,
                        library=MediaLibrary(root / "media"))


def alert_style(root: Path) -> OverlayStyle:
    a = alerts.ALERT_STYLE
    return OverlayStyle("alerts", a.skins, a.image_slots, a.sound_slots, a.default_options, a.ranges,
                        overlay_dir=root, allow_video=True, library=MediaLibrary(root / "media"))


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
        self.assertEqual(sniff(MP4), "mp4")           # an MP4 video is no longer mistaken for a sound
        self.assertEqual(sniff(M4A), "m4a")
        self.assertEqual(sniff(b"wOF2" + b"\0" * 8), "woff2")
        self.assertEqual(sniff(b"\0\x01\0\0" + b"\0" * 8), "ttf")
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
            style = chat_style(root)
            url = style.save_asset("badge-mod", PNG, filename="My Mod Badge.png")
            self.assertTrue(url.startswith("/media/my-mod-badge.png?v="))
            # another upload for the slot is a new stored file; the old one stays in the library
            b64 = "data:image/gif;base64," + base64.b64encode(GIF).decode()
            self.assertTrue(style.save_asset_base64("badge-mod", b64).startswith("/media/chat-badge-mod.gif"))
            self.assertEqual(sorted(f["name"] for f in style.library.list()), ["chat-badge-mod", "my-mod-badge"])
            style.save_asset("background", WEBP)
            style.save_asset("message", MP3)
            style.save_asset("paid", OGG)
            media, sounds = style.list_assets()
            self.assertEqual(set(media), {"badge-mod", "background"})
            self.assertTrue(media["badge-mod"].startswith("/media/chat-badge-mod.gif?v="))
            self.assertTrue(sounds["paid"].startswith("/media/chat-paid.ogg?v="))
            self.assertEqual(style.read_settings()["sounds"], sounds)
            # one file, many places: the paid sound uses the message sound's file
            style.pick("paid", "chat-message", kind="sound")
            self.assertEqual(style.list_assets()[1]["paid"], style.list_assets()[1]["message"])
            # wrong kind of file for the slot, unknown slot, empty, not a known type, video in chat
            with self.assertRaises(ValueError):
                style.save_asset("message", PNG)
            with self.assertRaises(ValueError):
                style.save_asset("badge-vip", MP3)
            with self.assertRaises(ValueError):
                style.save_asset("nope", PNG)
            with self.assertRaises(ValueError):
                style.save_asset("background", b"")
            with self.assertRaises(ValueError):
                style.save_asset("background", b"<svg onload=alert(1)>")
            with self.assertRaises(ValueError):
                style.save_asset("background", WEBM)
            with self.assertRaises(ValueError):
                style.pick("badge-vip", "chat-message")
            with self.assertRaises(ValueError):
                style.pick("message", "chat-background", kind="sound")
            self.assertTrue(style.delete_asset("badge-mod"))
            self.assertFalse(style.delete_asset("badge-mod"))
            self.assertNotIn("badge-mod", style.list_assets()[0])
            self.assertIsNotNone(style.library.get("chat-badge-mod"))     # clearing a slot keeps the file

    def test_hand_dropped_files_and_import(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            style = chat_style(root)
            (root / "assets" / "chat").mkdir(parents=True)
            (root / "assets" / "chat" / "badge-vip.png").write_bytes(PNG)
            (root / "assets" / "chat" / "message.mp3").write_bytes(MP3)
            media, sounds = style.list_assets()
            self.assertEqual(media, {"badge-vip": "assets/chat/badge-vip.png"})        # still works by hand
            self.assertEqual(style.import_legacy(), 2)
            self.assertEqual(style.import_legacy(), 0)                                # once only
            media, sounds = style.list_assets()
            self.assertTrue(media["badge-vip"].startswith("/media/chat-badge-vip.png"))
            self.assertTrue(sounds["message"].startswith("/media/chat-message.mp3"))
            self.assertTrue((root / "assets" / "chat" / "badge-vip.png").is_file())   # left for an older Core
            # clearing the slot also removes the hand-dropped copy, so it doesn't come back
            self.assertTrue(style.delete_asset("badge-vip"))
            self.assertNotIn("badge-vip", style.list_assets()[0])
            self.assertFalse((root / "assets" / "chat" / "badge-vip.png").exists())
            # saving the look keeps the picks
            style.write_settings(skin="plain", bump_css=True)
            self.assertIn("message", style.list_assets()[1])

    def test_rename_and_forget_follow(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            style = alert_style(root)
            style.save_asset("follow", GIF, filename="party.gif")
            style.pick("raid", "party")
            style.save_asset("bits", MP4, filename="cheer.mp4")             # alerts take MP4 video
            self.assertTrue(style.list_assets()[0]["bits"].startswith("/media/cheer.mp4"))
            self.assertEqual({(r["slot"], r["name"]) for r in style.media_refs()},
                             {("follow", "party"), ("raid", "party"), ("bits", "cheer")})
            style.library.rename("party", "confetti")
            self.assertEqual(style.media_renamed("party", "confetti"), 2)
            self.assertTrue(style.list_assets()[0]["raid"].startswith("/media/confetti.gif"))
            self.assertEqual(style.media_forgotten("confetti"), 2)
            self.assertEqual(set(style.list_assets()[0]), {"bits"})

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
            self.assertEqual(alerts.ALERT_STYLE.list_assets(overlay_dir=root)[0]["follow"], "assets/alerts/follow.webm")  # WebM first
            self.assertEqual(alerts.read_alert_settings(overlay_dir=root)["sounds"], {"raid": "assets/alerts/raid.mp3"})
            style = alert_style(root)
            self.assertTrue(style.save_asset("subscribe", WAV).startswith("/media/alerts-subscribe-sound.wav"))
            self.assertTrue(style.save_asset("subscribe", PNG).startswith("/media/alerts-subscribe.png"))
            media, sounds = style.list_assets()
            self.assertTrue(media["subscribe"].startswith("/media/alerts-subscribe.png"))   # picture and sound side by side
            self.assertTrue(sounds["subscribe"].startswith("/media/alerts-subscribe-sound.wav"))
            self.assertTrue(style.delete_asset("subscribe", kind="sound"))
            media, sounds = style.list_assets()
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
            style = chat_style(root)
            astyle = alert_style(root)
            astyle._library = style.library
            import core.chat_style as cs
            saved, saved_alerts = cs.CHAT_STYLE, alerts.ALERT_STYLE
            cs.CHAT_STYLE, alerts.ALERT_STYLE = style, astyle
            try:
                state = CoreState()
                state.media = style.library
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
                    self.assertTrue(up["url"].startswith("/media/chat-message.mp3?v="))
                    self.assertEqual(up["sounds"]["message"], up["url"])
                    self.assertEqual(up["picks"]["sound"], {"message": "chat-message"})
                    bad = client.post("/api/admin/overlays/chat/assets/message", headers=hdr,
                                      json={"data": base64.b64encode(PNG).decode()})
                    self.assertEqual(bad.status_code, 400)
                    self.assertEqual(client.post("/api/admin/overlays/chat/assets/nope", headers=hdr,
                                                 json={"data": base64.b64encode(PNG).decode()}).status_code, 400)
                    self.assertEqual(client.get("/api/admin/overlays/other/assets", headers=hdr).status_code, 404)
                    rm = client.delete("/api/admin/overlays/chat/assets/message", headers=hdr).json()
                    self.assertEqual(rm["sounds"], {})
                    self.assertEqual(client.delete("/api/admin/overlays/chat/assets/message", headers=hdr).status_code, 404)
                    # the settings json carries skin / version / options, and picks while a slot uses a file
                    data = json.loads((root / "chat-settings.json").read_text(encoding="utf-8"))
                    self.assertEqual(set(data), {"skin", "css_version", "options"})

                    # stored files: upload once, use twice, see where, replace, rename, delete
                    self.assertEqual(client.get("/api/admin/media").status_code, 401)
                    lib = client.get("/api/admin/media", headers=hdr).json()
                    self.assertEqual([f["name"] for f in lib["files"]], ["chat-message"])   # Clear kept it
                    up = client.post("/api/admin/media", headers=hdr,
                                     json={"data": base64.b64encode(GIF).decode(), "filename": "Party Time.gif"}).json()
                    self.assertEqual(up["file"]["name"], "party-time")
                    self.assertFalse(up["reused"])
                    again = client.post("/api/admin/media", headers=hdr,
                                        json={"data": base64.b64encode(GIF).decode(), "filename": "copy.gif"}).json()
                    self.assertTrue(again["reused"])
                    self.assertEqual(again["file"]["name"], "party-time")
                    self.assertEqual(client.post("/api/admin/media", headers=hdr,
                                                 json={"data": base64.b64encode(b"<html>").decode()}).status_code, 400)
                    self.assertEqual(client.post("/api/admin/overlays/chat/assets/background", headers=hdr,
                                                 json={"file": "party-time"}).status_code, 200)
                    self.assertEqual(client.post("/api/admin/overlays/alerts/assets/follow", headers=hdr,
                                                 json={"file": "party-time", "kind": "image"}).status_code, 200)
                    self.assertEqual(client.post("/api/admin/overlays/alerts/assets/follow", headers=hdr,
                                                 json={"file": "party-time", "kind": "sound"}).status_code, 400)
                    self.assertEqual(client.post("/api/admin/overlays/chat/assets/background", headers=hdr,
                                                 json={"file": "nope"}).status_code, 400)
                    lib = client.get("/api/admin/media", headers=hdr).json()
                    used = {f["name"]: f["used_by"] for f in lib["files"]}["party-time"]
                    self.assertEqual(sorted((u["overlay"], u["slot"]) for u in used), [("alerts", "follow"), ("chat", "background")])
                    # replace: a picture can become a video, never a sound
                    rep = client.put("/api/admin/media/party-time", headers=hdr, json={"data": base64.b64encode(PNG).decode()}).json()
                    self.assertEqual(rep["file"]["ext"], "png")
                    self.assertTrue(client.get("/api/admin/overlays/chat/assets", headers=hdr).json()["media"]["background"]
                                    .startswith("/media/party-time.png"))
                    self.assertEqual(client.put("/api/admin/media/party-time", headers=hdr,
                                                json={"data": base64.b64encode(MP3).decode()}).status_code, 400)
                    ren = client.put("/api/admin/media/party-time", headers=hdr, json={"name": "Confetti"}).json()
                    self.assertEqual(ren["file"]["name"], "confetti")
                    self.assertEqual(client.get("/api/admin/overlays/alerts/assets", headers=hdr).json()["picks"]["image"],
                                     {"follow": "confetti"})
                    self.assertEqual(client.put("/api/admin/media/confetti", headers=hdr, json={"name": "chat-message"}).status_code, 400)
                    self.assertEqual(client.put("/api/admin/media/missing", headers=hdr, json={"name": "x"}).status_code, 404)
                    gone = client.delete("/api/admin/media/confetti", headers=hdr).json()
                    self.assertEqual(gone["emptied"], 2)
                    self.assertEqual(client.get("/api/admin/overlays/alerts/assets", headers=hdr).json()["media"], {})
                    self.assertEqual(client.delete("/api/admin/media/confetti", headers=hdr).status_code, 404)
            finally:
                cs.CHAT_STYLE, alerts.ALERT_STYLE = saved, saved_alerts


if __name__ == "__main__":
    unittest.main()
