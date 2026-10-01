"""Reaction pictures: library, "img:name" objects in packets, boot seeded into old configs."""

from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


if __name__ == "__main__":
    unittest.main()
