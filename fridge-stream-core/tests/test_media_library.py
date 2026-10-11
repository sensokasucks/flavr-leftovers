"""Stored files (core/media_library.py): one copy of each upload, reused by alerts, chat and
custom CSS, served at /media/. Run from fridge-stream-core:

    python -m unittest tests.test_media_library -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import media_library  # noqa: E402
from core.media_library import MediaLibrary, clean_name, name_from_filename  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 20
PNG2 = b"\x89PNG\r\n\x1a\n" + b"\1" * 20
GIF = b"GIF89a" + b"\0" * 20
WEBM = b"\x1a\x45\xdf\xa3" + b"\0" * 20
MP4 = b"\0\0\0\x20ftypisom" + b"\0" * 20
MP3 = b"ID3" + b"\0" * 20
WOFF2 = b"wOF2" + b"\0" * 20


class NameTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(clean_name("  Party Time! "), "party-time")
        self.assertEqual(name_from_filename(r"C:\Users\me\My Ding.MP3"), "my-ding")
        self.assertEqual(name_from_filename("archive.tar.gz"), "archive-tar")
        self.assertEqual(len(clean_name("x" * 80)), 40)


class LibraryTests(unittest.TestCase):
    def test_save_dedupe_and_names(self):
        with tempfile.TemporaryDirectory() as d:
            lib = MediaLibrary(Path(d))
            self.assertEqual(lib.list(), [])
            e, reused = lib.save(PNG, "boot")
            self.assertFalse(reused)
            self.assertEqual((e["name"], e["ext"], e["kind"]), ("boot", "png", "image"))
            self.assertTrue(e["url"].startswith("/media/boot.png?v="))
            self.assertEqual(e["css_url"], "/media/boot")
            # the same bytes again: no second copy, whatever the name
            e2, reused = lib.save(PNG, "other")
            self.assertTrue(reused)
            self.assertEqual(e2["name"], "boot")
            # a different file wanting a taken name gets -2
            self.assertEqual(lib.save(PNG2, "boot")[0]["name"], "boot-2")
            self.assertEqual(lib.save(GIF, "")[0]["name"], "file")
            self.assertEqual(lib.save(MP4, "clip")[0]["kind"], "video")
            self.assertEqual(lib.save(MP3, "ding")[0]["kind"], "sound")
            self.assertEqual(lib.save(WOFF2, "Fancy Font")[0]["kind"], "font")
            self.assertEqual(sorted(f["name"] for f in lib.list()), ["boot", "boot-2", "clip", "ding", "fancy-font", "file"])
            # the index survives a new library object (hashes kept, so dedupe still works)
            again = MediaLibrary(Path(d))
            self.assertTrue(again.save(MP3, "x")[1])

    def test_rejects(self):
        with tempfile.TemporaryDirectory() as d:
            lib = MediaLibrary(Path(d))
            for bad in (b"", b"<svg onload=alert(1)>", b"MZ\x90\0 not a picture"):
                with self.assertRaises(ValueError):
                    lib.save(bad, "x")
            old = media_library.MAX_BYTES
            media_library.MAX_BYTES = 10
            try:
                with self.assertRaises(ValueError):
                    lib.save(PNG, "big")
                lib.save(WEBM, "video-ok")      # videos have their own, bigger limit
            finally:
                media_library.MAX_BYTES = old

    def test_replace_rename_delete(self):
        with tempfile.TemporaryDirectory() as d:
            lib = MediaLibrary(Path(d))
            lib.save(GIF, "party")
            lib.save(MP3, "ding")
            # a picture may become a video (new extension, same name); never a sound or font
            e = lib.replace("party", WEBM)
            self.assertEqual((e["name"], e["ext"]), ("party", "webm"))
            self.assertFalse((Path(d) / "party.gif").exists())
            with self.assertRaises(ValueError):
                lib.replace("party", MP3)
            with self.assertRaises(ValueError):
                lib.replace("ding", PNG)
            with self.assertRaises(KeyError):
                lib.replace("missing", PNG)
            # an identical upload after a replace finds the new content
            self.assertTrue(lib.save(WEBM, "x")[1])
            e = lib.rename("party", "Confetti Rain")
            self.assertEqual(e["name"], "confetti-rain")
            self.assertIsNone(lib.get("party"))
            with self.assertRaises(ValueError):
                lib.rename("confetti-rain", "ding")
            with self.assertRaises(ValueError):
                lib.rename("confetti-rain", "!!!")
            self.assertTrue(lib.delete("confetti-rain"))
            self.assertFalse(lib.delete("confetti-rain"))
            self.assertEqual([f["name"] for f in lib.list()], ["ding"])

    def test_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            lib = MediaLibrary(Path(d))
            lib.save(PNG, "boot")
            self.assertEqual(lib.resolve("boot").name, "boot.png")
            self.assertEqual(lib.resolve("boot.png").name, "boot.png")
            self.assertEqual(lib.resolve("boot.gif").name, "boot.png")      # the name decides
            for bad in ("", "library", "library.json", "../boot.png", "Boot", "a/b", "boot.png.tmp/x"):
                self.assertIsNone(lib.resolve(bad), bad)


class ServeTests(unittest.TestCase):
    def test_media_route(self):
        from fastapi.testclient import TestClient

        from api.server import CoreState, create_app

        with tempfile.TemporaryDirectory() as d:
            lib = MediaLibrary(Path(d))
            lib.save(PNG, "boot")
            lib.save(WOFF2, "font")
            state = CoreState()
            state.config = {}
            state.media = lib
            with TestClient(create_app(state), base_url="http://127.0.0.1:3850") as client:
                r = client.get("/media/boot")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.content, PNG)
                self.assertEqual(r.headers["content-type"], "image/png")
                self.assertEqual(client.get("/media/boot.png?v=1").status_code, 200)
                self.assertEqual(client.get("/media/font").headers["content-type"], "font/woff2")
                self.assertEqual(client.get("/media/nope").status_code, 404)
                self.assertEqual(client.get("/media/library.json").status_code, 404)


if __name__ == "__main__":
    unittest.main()
