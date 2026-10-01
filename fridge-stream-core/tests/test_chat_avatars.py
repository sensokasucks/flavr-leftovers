"""Chatter profile pictures (Kick lookup cache, YouTube author photos). Run from fridge-stream-core:

    python -m unittest tests.test_chat_avatars -v
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.kick_avatars import KickAvatars, picture_from_channel  # noqa: E402
from adapters.youtube_avatar import best_photo  # noqa: E402


class KickAvatarTests(unittest.TestCase):
    def test_picture_from_channel(self):
        self.assertEqual(picture_from_channel({"user": {"profile_pic": "https://x/p.webp"}}), "https://x/p.webp")
        self.assertEqual(picture_from_channel({"user": {"profile_pic": None}}), "")
        self.assertEqual(picture_from_channel({}), "")

    def test_lookup_once_and_cache(self):
        calls = []
        found = []

        async def fetch(slug):
            calls.append(slug)
            return 200, f"https://pics/{slug}.png"

        async def on_found(url):
            found.append(url)

        async def run(path):
            a = KickAvatars(fetcher=fetch, path=path)
            self.assertIsNone(a.get("Viewer"))
            a.request("Viewer", on_found)
            a.request("viewer", on_found)          # already pending
            await asyncio.sleep(0.05)
            a.request("viewer", on_found)          # cached now
            await asyncio.sleep(0.05)
            self.assertEqual(a.get("viewer"), "https://pics/viewer.png")
            a.stop()
            b = KickAvatars(fetcher=fetch, path=path)   # persisted
            self.assertEqual(b.get("VIEWER"), "https://pics/viewer.png")

        with tempfile.TemporaryDirectory() as d:
            asyncio.run(run(Path(d) / "kick_avatars.json"))
        self.assertEqual(calls, ["viewer"])
        self.assertEqual(found, ["https://pics/viewer.png"])

    def test_blocked_is_not_hammered(self):
        calls = []

        async def fetch(slug):
            calls.append(slug)
            return 403, ""

        async def nop(url):
            pass

        async def run(path):
            a = KickAvatars(fetcher=fetch, path=path)
            a.request("x", nop)
            await asyncio.sleep(0.05)
            a.request("x", nop)
            await asyncio.sleep(0.05)
            self.assertIsNone(a.get("x"))

        with tempfile.TemporaryDirectory() as d:
            asyncio.run(run(Path(d) / "k.json"))
        self.assertEqual(calls, ["x"])

    def test_disabled(self):
        async def fetch(slug):
            raise AssertionError("should not fetch")

        async def run():
            a = KickAvatars(enabled=False, fetcher=fetch, path=Path(tempfile.gettempdir()) / "unused.json")
            a.request("x", fetch)
            await asyncio.sleep(0.01)

        asyncio.run(run())


class YouTubePhotoTests(unittest.TestCase):
    def test_best_photo(self):
        thumbs = {"thumbnails": [
            {"url": "https://yt3.ggpht.com/abc=s32-c-k-c0x00ffffff-no-rj", "width": 32},
            {"url": "//yt3.ggpht.com/abc=s64-c-k-c0x00ffffff-no-rj", "width": 64},
        ]}
        self.assertEqual(best_photo(thumbs), "https://yt3.ggpht.com/abc=s128-c-k-c0x00ffffff-no-rj")
        self.assertEqual(best_photo({}), "")
        self.assertEqual(best_photo("https://x/y.jpg"), "https://x/y.jpg")


if __name__ == "__main__":
    unittest.main()
