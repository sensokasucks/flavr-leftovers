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

import json  # noqa: E402
import time  # noqa: E402

from adapters import kick_avatars, twitch_avatars  # noqa: E402
from adapters.kick_avatars import KickAvatars, picture_from_channel  # noqa: E402
from adapters.twitch_avatars import TwitchAvatars  # noqa: E402
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


def _old_link_file(path: Path, key: str, url: str, age_sec: float) -> None:
    path.write_text(json.dumps({key: {"url": url, "ts": time.time() - age_sec}}), encoding="utf-8")


class PictureRecheckTests(unittest.TestCase):
    """A saved link is re-checked in the background once it is older than REFRESH_SEC;
    the old picture keeps showing meanwhile and only a changed link is announced."""

    def _kick(self, age_sec, new_url):
        calls, found = [], []

        async def fetch(slug):
            calls.append(slug)
            return 200, new_url

        async def on_found(url):
            found.append(url)

        async def run(path):
            _old_link_file(path, "viewer", "https://pics/old.png", age_sec)
            a = KickAvatars(fetcher=fetch, path=path)
            self.assertEqual(a.get("viewer"), "https://pics/old.png")   # shown right away
            a.request("viewer", on_found)
            await asyncio.sleep(0.05)
            return a.get("viewer")

        with tempfile.TemporaryDirectory() as d:
            now = asyncio.run(run(Path(d) / "kick_avatars.json"))
        return calls, found, now

    def test_kick_fresh_link_is_not_rechecked(self):
        calls, found, now = self._kick(60, "https://pics/new.png")
        self.assertEqual((calls, found, now), ([], [], "https://pics/old.png"))

    def test_kick_old_link_picks_up_new_picture(self):
        calls, found, now = self._kick(kick_avatars.REFRESH_SEC + 60, "https://pics/new.png")
        self.assertEqual((calls, found, now), (["viewer"], ["https://pics/new.png"], "https://pics/new.png"))

    def test_kick_same_link_is_not_announced(self):
        calls, found, _ = self._kick(kick_avatars.REFRESH_SEC + 60, "https://pics/old.png")
        self.assertEqual((calls, found), (["viewer"], []))

    def test_twitch_old_links_rechecked_in_one_batch(self):
        calls, found = [], []

        async def fetch(ids):
            calls.append(sorted(ids))
            return 200, {"1": "https://pics/1-new.png", "2": "https://pics/2.png"}

        def on_found(uid):
            async def cb(url):
                found.append((uid, url))
            return cb

        async def run(path):
            old = time.time() - twitch_avatars.REFRESH_SEC - 60
            path.write_text(json.dumps({"1": {"url": "https://pics/1.png", "ts": old},
                                        "2": {"url": "https://pics/2.png", "ts": old},
                                        "3": {"url": "https://pics/3.png", "ts": time.time()}}),
                            encoding="utf-8")
            a = TwitchAvatars(fetcher=fetch, path=path, batch_delay=0.01)
            for uid in ("1", "2", "3"):
                a.request(uid, on_found(uid))
            await asyncio.sleep(0.1)
            return a.get("1")

        with tempfile.TemporaryDirectory() as d:
            now = asyncio.run(run(Path(d) / "twitch_avatars.json"))
        self.assertEqual(calls, [["1", "2"]])                      # "3" is fresh
        self.assertEqual(found, [("1", "https://pics/1-new.png")])  # "2" didn't change
        self.assertEqual(now, "https://pics/1-new.png")


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
