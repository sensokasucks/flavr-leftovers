"""Chat smoothing (core/chat_pacer.py) and the YouTube chat check interval.
Run from fridge-stream-core:

    python -m unittest tests.test_chat_pacer -v
"""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.youtube import next_poll_delay, poll_interval_setting  # noqa: E402
from core.chat_pacer import ChatPacer, smoothing_settings  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402


def ev(platform: Platform, n: int, user: str = "viewer") -> ChatEvent:
    return ChatEvent(
        platform=platform,
        user=ChatUser(platform=platform, id=f"id-{user}", username=user, display_name=user),
        message=f"line {n}",
        message_id=f"{platform.value}-{n}",
    )


class Harness:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.bus = EventBus()
        self.got: list[tuple[float, ChatEvent]] = []
        self.t0 = time.monotonic()

        async def handler(e: ChatEvent) -> None:
            self.got.append((time.monotonic() - self.t0, e))

        self.bus.on_chat(handler)
        self.bus.pacer = ChatPacer(self.bus.publish_chat, lambda: self.cfg)

    async def settle(self, timeout: float = 5.0) -> None:
        end = time.monotonic() + timeout
        while self.bus.pacer.queued() and time.monotonic() < end:
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)


def run(coro):
    return asyncio.run(coro)


class SettingsTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(smoothing_settings({}), (set(), 5.0))
        self.assertEqual(smoothing_settings({"chat_smoothing": {"youtube": "yes"}})[0], set())

    def test_cap_is_clamped(self):
        self.assertEqual(smoothing_settings({"chat_smoothing": {"max_delay_sec": 0}})[1], 1.0)
        self.assertEqual(smoothing_settings({"chat_smoothing": {"max_delay_sec": 999}})[1], 30.0)
        self.assertEqual(smoothing_settings({"chat_smoothing": {"max_delay_sec": "x"}})[1], 5.0)


class PacerTests(unittest.TestCase):
    def test_off_delivers_at_once(self):
        async def go():
            h = Harness({})
            for i in range(5):
                await h.bus.submit_chat(ev(Platform.YOUTUBE, i))
            self.assertEqual(len(h.got), 5)
            self.assertEqual(h.bus.pacer.queued(), 0)
        run(go())

    def test_clump_is_spread_out_in_order(self):
        async def go():
            h = Harness({"chat_smoothing": {"youtube": True, "max_delay_sec": 2}})
            for i in range(10):
                await h.bus.submit_chat(ev(Platform.YOUTUBE, i))
            # the first line goes straight out, the rest wait their turn
            self.assertEqual(len(h.got), 1)
            await h.settle()
            self.assertEqual([e.message for _, e in h.got], [f"line {i}" for i in range(10)])
            times = [t for t, _ in h.got]
            self.assertGreater(times[-1] - times[0], 0.8)     # spread, not one clump
            self.assertLess(times[-1], 2.0 + 0.3)              # and never held past the cap
        run(go())

    def test_busy_chat_never_falls_behind(self):
        async def go():
            h = Harness({"chat_smoothing": {"youtube": True, "max_delay_sec": 1}})
            for i in range(300):
                await h.bus.submit_chat(ev(Platform.YOUTUBE, i))
            await h.settle()
            self.assertEqual(len(h.got), 300)
            self.assertLess(h.got[-1][0], 1.0 + 0.3)
        run(go())

    def test_other_platforms_are_not_held_up(self):
        async def go():
            h = Harness({"chat_smoothing": {"youtube": True, "max_delay_sec": 3}})
            for i in range(20):
                await h.bus.submit_chat(ev(Platform.YOUTUBE, i))
            await h.bus.submit_chat(ev(Platform.TWITCH, 0))
            self.assertIn("twitch-0", [e.message_id for _, e in h.got])
            await h.settle()
        run(go())

    def test_deleted_line_is_never_shown(self):
        async def go():
            h = Harness({"chat_smoothing": {"youtube": True, "max_delay_sec": 2}})
            for i in range(6):
                await h.bus.submit_chat(ev(Platform.YOUTUBE, i, user="spam" if i == 4 else "viewer"))
            await h.bus.publish_chat_removed({"platform": "youtube", "message_id": "youtube-3"})
            await h.bus.publish_chat_removed({"platform": "youtube", "username": "spam"})
            await h.settle()
            ids = [e.message_id for _, e in h.got]
            self.assertNotIn("youtube-3", ids)
            self.assertNotIn("youtube-4", ids)
            self.assertEqual(len(ids), 4)
        run(go())

    def test_switching_off_lets_held_lines_out(self):
        async def go():
            h = Harness({"chat_smoothing": {"youtube": True, "max_delay_sec": 5}})
            for i in range(10):
                await h.bus.submit_chat(ev(Platform.YOUTUBE, i))
            h.cfg = {}
            await h.bus.submit_chat(ev(Platform.YOUTUBE, 10))
            self.assertEqual([e.message for _, e in h.got], [f"line {i}" for i in range(11)])
        run(go())

    def test_quiet_chat_is_not_delayed(self):
        async def go():
            h = Harness({"chat_smoothing": {"youtube": True, "max_delay_sec": 5}})
            await h.bus.submit_chat(ev(Platform.YOUTUBE, 0))
            self.assertEqual(len(h.got), 1)
        run(go())


class YouTubePollTests(unittest.TestCase):
    def test_setting(self):
        self.assertEqual(poll_interval_setting(None), 0.0)
        self.assertEqual(poll_interval_setting(""), 0.0)
        self.assertEqual(poll_interval_setting(0), 0.0)
        self.assertEqual(poll_interval_setting(0.2), 1.0)
        self.assertEqual(poll_interval_setting(3), 3.0)
        self.assertEqual(poll_interval_setting(500), 30.0)
        self.assertEqual(poll_interval_setting("abc"), 0.0)

    def test_auto_follows_youtube(self):
        self.assertEqual(next_poll_delay(6.0, 0), 6.0)
        self.assertEqual(next_poll_delay(0.5, 0), 2.0)

    def test_innertube_uses_the_setting(self):
        self.assertEqual(next_poll_delay(6.0, 1.5), 1.5)
        self.assertEqual(next_poll_delay(2.0, 10.0), 10.0)

    def test_official_never_faster_than_youtube_asks(self):
        self.assertEqual(next_poll_delay(5.0, 1.0, official=True), 5.0)
        self.assertEqual(next_poll_delay(5.0, 12.0, official=True), 12.0)


if __name__ == "__main__":
    unittest.main()
