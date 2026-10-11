"""Reaction pictures: library, "img:name" objects in packets, boot seeded into old configs."""

from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.media_library import MediaLibrary  # noqa: E402
from core.reaction_images import ReactionImages, clean_name, sniff  # noqa: E402
from core.reactions import DEFAULT_ENTRIES, ReactionEngine, normalize_config  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.builtin = t / "builtin"
        self.custom = t / "custom"
        self.builtin.mkdir()
        (self.builtin / "boot.png").write_bytes(PNG)
        self.lib = ReactionImages(self.builtin, self.custom)

    def tearDown(self):
        self.tmp.cleanup()

    def test_shipped_boot_is_a_real_png(self):
        data = (ROOT / "overlay" / "assets" / "reactions" / "boot.png").read_bytes()
        self.assertEqual(sniff(data), "png")

    def test_builtin_listed_and_resolved(self):
        names = [i["name"] for i in self.lib.list()]
        self.assertEqual(names, ["boot"])
        pic = self.lib.resolve_object("img:boot")
        self.assertTrue(pic["url"].startswith("/reactions/images/boot.png?v="))
        self.assertFalse(pic["animated"])
        self.assertIsNone(self.lib.resolve_object("🍅"))
        self.assertIsNone(self.lib.resolve_object("img:nope"))

    def test_upload_types_and_limits(self):
        info = self.lib.save("Rubber Chicken!", GIF)
        self.assertEqual(info["name"], "rubber-chicken")
        self.assertTrue(info["animated"])
        self.assertEqual(self.lib.save("pic", JPG)["file"], "pic.jpg")
        with self.assertRaises(ValueError):
            self.lib.save("bad", b"<svg></svg>")
        with self.assertRaises(ValueError):
            self.lib.save("", PNG)
        with self.assertRaises(ValueError):
            self.lib.save("huge", PNG + b"\x00" * (5 * 1024 * 1024))
        b64 = "data:image/png;base64," + base64.b64encode(PNG).decode()
        self.assertEqual(self.lib.save_base64("frompage", b64)["kind"], "png")

    def test_replace_and_delete(self):
        self.lib.save("boot", GIF)                    # hides the built-in
        self.assertEqual(self.lib.get("boot")["source"], "custom")
        self.lib.save("boot", JPG)                    # replacing drops the old format
        self.assertEqual(sorted(p.name for p in self.custom.iterdir()), ["boot.jpg"])
        self.assertTrue(self.lib.delete("boot"))
        self.assertEqual(self.lib.get("boot")["source"], "built-in")
        self.assertFalse(self.lib.delete("boot"))    # built-ins can't be deleted

    def test_file_path_blocks_traversal(self):
        self.assertIsNotNone(self.lib.file_path("boot.png"))
        for bad in ("../boot.png", "..\\\\boot.png", "boot.txt", "", "sub/boot.png"):
            self.assertIsNone(self.lib.file_path(bad), bad)

    def test_clean_name(self):
        self.assertEqual(clean_name("  Big BOOT.v2 "), "big-boot-v2")


class SeedTests(unittest.TestCase):
    def test_fresh_config_has_boot(self):
        cfg = normalize_config({})
        self.assertIn("boot", [e["id"] for e in cfg["entries"]])
        self.assertIn("boot", cfg["seeded_defaults"])

    def test_old_config_gets_boot_once(self):
        old = {"entries": [e for e in DEFAULT_ENTRIES if e["id"] != "boot"]}
        cfg = normalize_config(old)
        self.assertIn("boot", [e["id"] for e in cfg["entries"]])
        # the user deletes it and saves: it stays gone
        cfg["entries"] = [e for e in cfg["entries"] if e["id"] != "boot"]
        again = normalize_config(cfg)
        self.assertNotIn("boot", [e["id"] for e in again["entries"]])

    def test_packet_params_carry_the_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = ReactionImages(ROOT / "overlay" / "assets" / "reactions", Path(tmp))
            eng = ReactionEngine(get_config=lambda: {"reactions": {"enabled": True}}, images=lib)
            boot = next(e for e in eng.cfg["entries"] if e["id"] == "boot")
            params = eng._params_for(boot)
            self.assertEqual(params["object"], "img:boot")
            self.assertEqual(params["object_image"]["name"], "boot")
            tomato = next(e for e in eng.cfg["entries"] if e["id"] == "tomato")
            self.assertNotIn("object_image", eng._params_for(tomato))



WEBP = b"RIFF" + b"\0\0\0\0" + b"WEBP" + b"\0" * 24
MP3 = b"ID3" + b"\0" * 32


class StoredFilesTests(unittest.TestCase):
    """Reaction pictures live in Stored files (core/media_library.py) since step 2."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.builtin = t / "builtin"
        self.custom = t / "custom"
        self.builtin.mkdir()
        (self.builtin / "boot.png").write_bytes(PNG)
        self.media = MediaLibrary(t / "media")
        self.lib = ReactionImages(self.builtin, self.custom, library=self.media)

    def tearDown(self):
        self.tmp.cleanup()

    def test_any_stored_picture_is_an_object(self):
        self.media.save(GIF, "party")
        self.media.save(WEBP, "sticker")
        self.media.save(MP3, "ding")                      # sounds are not pictures
        names = {i["name"]: i for i in self.lib.list()}
        self.assertEqual(set(names), {"boot", "party", "sticker"})
        self.assertEqual(names["party"]["source"], "stored")
        self.assertTrue(names["party"]["animated"])
        pic = self.lib.resolve_object("img:party")
        self.assertTrue(pic["url"].startswith("/media/party.gif?v="))
        self.assertEqual(self.lib.resolve_object("img:boot")["url"].split("?")[0], "/reactions/images/boot.png")
        self.assertIsNone(self.lib.resolve_object("img:ding"))

    def test_upload_goes_to_stored_files_by_exact_name(self):
        info = self.lib.save("Rubber Chicken", WEBP)
        self.assertEqual((info["name"], info["source"]), ("rubber-chicken", "stored"))
        self.assertIsNotNone(self.media.get("rubber-chicken"))
        self.assertFalse(self.custom.exists())
        # the same picture under another name is still stored under the name asked for
        self.assertEqual(self.lib.save("chicken-two", WEBP)["name"], "chicken-two")
        self.lib.save("rubber-chicken", WEBP)            # same file, same name: fine
        with self.assertRaises(ValueError):
            self.lib.save("rubber-chicken", PNG)          # a different file can't take the name
        with self.assertRaises(ValueError):
            self.lib.save("x", MP3)
        # a stored picture called boot replaces the built-in; Delete here never touches either
        self.lib.save("boot", GIF)
        self.assertEqual(self.lib.get("boot")["source"], "stored")
        self.assertFalse(self.lib.delete("boot"))

    def test_older_uploads_move_in(self):
        self.custom.mkdir()
        (self.custom / "chicken.png").write_bytes(PNG)
        (self.custom / "taken.gif").write_bytes(GIF)
        self.media.save(JPG, "taken")                     # a different stored file already has this name
        self.assertEqual(self.lib.import_legacy(), 1)
        self.assertFalse((self.custom / "chicken.png").exists())
        self.assertTrue((self.custom / "taken.gif").exists())          # stays, still usable
        self.assertEqual(self.lib.get("chicken")["source"], "stored")
        self.assertEqual(self.lib.get("taken")["source"], "stored")   # the stored one wins
        self.assertEqual(self.lib.import_legacy(), 0)
        self.assertTrue(self.lib.delete("taken"))                       # an older upload can be deleted here


class ReactionUsageRouteTests(unittest.TestCase):
    """Stored files page: reactions show in "Used by"; rename and delete follow."""

    TOKEN = "unit-test-admin-token-123456"

    def test_used_by_rename_delete(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import api.admin_routes as ar
        from api.admin_routes import create_admin_router
        from api.server import CoreState

        with tempfile.TemporaryDirectory() as d:
            t = Path(d)
            (t / "builtin").mkdir()
            (t / "builtin" / "boot.png").write_bytes(PNG)
            media = MediaLibrary(t / "media")
            media.save(GIF, "party")
            media.save(PNG, "boot")
            images = ReactionImages(t / "builtin", t / "custom", library=media)
            cfg = {"points": {"admin_token": self.TOKEN},
                   "reactions": {"entries": [
                       {"id": "party", "effect": "throw", "params": {"object": "img:party"}},
                       {"id": "kick", "label": "Boot", "effect": "throw", "params": {"object": "img:boot"}},
                   ]}}
            state = CoreState()
            state.config = cfg
            state.media = media

            class Eng:
                pass

            state.reactions = Eng()
            state.reactions.images = images
            saved: list = []
            real_save, real_load = ar.save_config, ar.load_config
            ar.save_config = lambda c: saved.append(c) or "config.yaml"
            ar.load_config = lambda: saved[-1] if saved else cfg
            try:
                app = FastAPI()
                app.include_router(create_admin_router(state))
                hdr = {"X-Admin-Token": self.TOKEN}
                with TestClient(app) as client:
                    files = {f["name"]: f for f in client.get("/api/admin/media", headers=hdr).json()["files"]}
                    self.assertIn({"overlay": "reactions", "slot": "party", "kind": "image"}, files["party"]["used_by"])
                    self.assertIn({"overlay": "reactions", "slot": "Boot", "kind": "image"}, files["boot"]["used_by"])
                    imgs = {i["name"] for i in client.get("/api/admin/reactions/images", headers=hdr).json()["images"]}
                    self.assertEqual(imgs, {"boot", "party"})
                    # rename: the reaction follows
                    self.assertEqual(client.put("/api/admin/media/party", headers=hdr, json={"name": "confetti"}).status_code, 200)
                    objs = {e["id"]: e["params"].get("object") for e in state.config["reactions"]["entries"]}
                    self.assertEqual(objs["party"], "img:confetti")
                    # delete: a reaction with no built-in to fall back on goes back to its default object
                    client.delete("/api/admin/media/confetti", headers=hdr)
                    objs = {e["id"]: e["params"].get("object") for e in state.config["reactions"]["entries"]}
                    self.assertIsNone(objs["party"])
                    # ... but img:boot stays, the built-in boot takes over
                    client.delete("/api/admin/media/boot", headers=hdr)
                    objs = {e["id"]: e["params"].get("object") for e in state.config["reactions"]["entries"]}
                    self.assertEqual(objs["kick"], "img:boot")
                    self.assertEqual(images.get("boot")["source"], "built-in")
                    # the Reactions page can't delete a stored or built-in picture
                    media.save(GIF, "party")
                    self.assertEqual(client.delete("/api/admin/reactions/images/party", headers=hdr).status_code, 404)
            finally:
                ar.save_config, ar.load_config = real_save, real_load

if __name__ == "__main__":
    unittest.main()
