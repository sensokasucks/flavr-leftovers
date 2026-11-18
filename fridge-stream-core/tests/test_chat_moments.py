"""Chat moments (core/chat_moments.py) and Twitch clips (adapters/twitch.py create_clip): no network.

    python -m unittest tests.test_chat_moments -v
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.twitch import TwitchAdapter  # noqa: E402
from core.chat_moments import ChatMoments, read_settings  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402
from tests.test_platform_replies import FakeTwitchAuth  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Moments(unittest.TestCase):
    def setUp(self):
        self.t = 1000.0
        self.cpm = 10.0
        self.live = True
        self.cfg = {}
        self.sent = []
        self.clips = []

        async def clip():
            self.clips.append(self.t)
            return "https://clips.twitch.tv/Abc", ""

        self.m = ChatMoments(lambda: self.cfg, lambda: self.cpm, lambda: self.live, self.sent.append,
                             make_clip=clip, twitch_live=lambda: True, clock=lambda: self.t)

    def step(self, seconds, cpm):
        self.cpm = cpm
        out = []
        for _ in range(int(seconds / 2)):
            self.t += 2
            r = run(self.m.tick())
            if r:
                out.append(r)
        return out

    def test_a_burst_after_warmup_is_a_moment_once_per_cooldown(self):
        self.assertEqual(self.step(60, 80), [])            # warming up: no moment at the start
        self.step(300, 10)                                  # a quiet baseline
        got = self.step(10, 45)                             # 4.5x the usual and over 20
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["baseline"], 10.0)
        self.assertAlmostEqual(got[0]["at"], self.t - 10 + 2 - 20, delta=2)
        self.assertNotIn("clip", got[0])                    # twitch_clips off by default
        self.assertEqual(self.step(120, 45), [])            # cooldown (5 min)
        self.assertEqual(self.sent, got)

    def test_small_or_offline_bursts_are_not_moments(self):
        self.step(300, 2)
        self.assertEqual(self.step(10, 15), [])             # 7x but under min_cpm 20
        self.live = False
        self.assertEqual(self.step(10, 200), [])
        self.live = True
        self.assertEqual(self.step(10, 200), [])            # back live: baseline starts over

    def test_twitch_clip_when_switched_on(self):
        self.cfg = {"moments": {"twitch_clips": True}}
        self.step(300, 10)
        got = self.step(4, 60)
        self.assertEqual(got[0]["clip"], "https://clips.twitch.tv/Abc")
        self.assertEqual(len(self.clips), 1)

    def test_no_moment_or_clip_while_the_companion_link_is_off(self):
        self.cfg = {"moments": {"twitch_clips": True}}
        self.m._link_on = lambda: False     # main.py: companion.why_not() says why the link can't send
        self.step(300, 10)
        self.assertEqual(self.step(10, 200), [])
        self.assertEqual(self.clips, [])

    def test_settings_are_clamped(self):
        s = read_settings({"moments": {"factor": 0.5, "min_cpm": "x", "cooldown_min": 999}})
        self.assertEqual((s["factor"], s["min_cpm"], s["cooldown_min"]), (1.5, 20, 120))
        self.assertFalse(s["twitch_clips"])


class TwitchClip(unittest.TestCase):
    def adapter(self, answers, scopes=("user:read:chat", "clips:edit")):
        a = TwitchAdapter({"twitch": {"channel": "fridge", "avatars": False, "third_party_emotes": False}},
                          EventBus(), MetricsAggregator({}))
        a.auth = FakeTwitchAuth(scopes)
        a.calls = []

        async def helix(method, url, body, headers):
            a.calls.append((method, url))
            return answers.pop(0)

        a._helix = helix
        return a

    def test_clip_made(self):
        a = self.adapter([(202, {"data": [{"id": "Funny123", "edit_url": "x"}]})])
        self.assertEqual(run(a.create_clip()), ("https://clips.twitch.tv/Funny123", ""))
        self.assertEqual(a.calls, [("POST", "https://api.twitch.tv/helix/clips?broadcaster_id=42")])

    def test_no_scope_or_refused(self):
        url, why = run(self.adapter([], scopes=("user:read:chat",)).create_clip())
        self.assertEqual(url, "")
        self.assertIn("Reconnect", why)
        url, why = run(self.adapter([(404, {"message": "Clipping is not possible for an offline channel."})]).create_clip())
        self.assertIn("offline", why)


if __name__ == "__main__":
    unittest.main()
