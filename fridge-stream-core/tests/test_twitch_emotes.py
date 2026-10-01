"""Twitch emote ranges (native IRC tag + BTTV / FFZ / 7TV). Run from fridge-stream-core:

    python -m unittest tests.test_twitch_emotes -v
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.twitch_emotes import (  # noqa: E402
    ThirdPartyEmotes,
    _bttv,
    _ffz,
    _seventv,
    match_words,
    parse_twitch_emotes,
    strip_action,
)


class ParseTagTests(unittest.TestCase):
    def test_native_ranges(self):
        msg = "Kappa hi Kappa LUL"
        em = parse_twitch_emotes("25:0-4,9-13/425618:15-17", msg)
        self.assertEqual([(e["start"], e["end"], e["name"]) for e in em],
                         [(0, 4, "Kappa"), (9, 13, "Kappa"), (15, 17, "LUL")])
        self.assertTrue(em[0]["static_url"].endswith("/25/static/dark/2.0"))
        self.assertEqual(em[0]["provider"], "twitch")

    def test_code_points_with_emoji(self):
        msg = "😂 Kappa"          # one code point before the space
        em = parse_twitch_emotes("25:2-6", msg)
        self.assertEqual(em[0]["name"], "Kappa")

    def test_bad_tag_is_ignored(self):
        self.assertEqual(parse_twitch_emotes("", "x"), [])
        self.assertEqual(parse_twitch_emotes("25:9-99", "short"), [])
        self.assertEqual(parse_twitch_emotes("garbage", "short"), [])

    def test_strip_action(self):
        self.assertEqual(strip_action("\x01ACTION waves\x01"), "waves")
        self.assertEqual(strip_action("plain"), "plain")


class ThirdPartyTests(unittest.TestCase):
    def setUp(self):
        self.table = {}
        self.table.update(_ffz({"3": {"emoticons": [{"id": 9, "name": "ZrehplaR",
            "urls": {"1": "https://cdn.frankerfacez.com/emote/9/1", "2": "https://cdn.frankerfacez.com/emote/9/2"}}]}}))
        self.table.update(_bttv([{"id": "b1", "code": "catJAM", "imageType": "gif", "animated": True},
                                 {"id": "b2", "code": "monkaS", "imageType": "png", "animated": False}]))
        self.table.update(_seventv([{"id": "s1", "name": "PogU",
            "data": {"animated": False, "host": {"url": "//cdn.7tv.app/emote/s1"}}}]))

    def test_urls(self):
        self.assertEqual(self.table["monkaS"]["static_url"], "https://cdn.betterttv.net/emote/b2/2x")
        self.assertEqual(self.table["catJAM"]["static_url"], "")        # animated GIF, no still
        self.assertEqual(self.table["PogU"]["static_url"], "https://cdn.7tv.app/emote/s1/2x_static.webp")
        self.assertEqual(self.table["ZrehplaR"]["url"], "https://cdn.frankerfacez.com/emote/9/2")

    def test_whole_words_only(self):
        em = match_words("PogU monkaS monkaSS xPogU PogU", self.table, [])
        self.assertEqual([(e["start"], e["name"]) for e in em], [(0, "PogU"), (5, "monkaS"), (26, "PogU")])

    def test_native_wins_overlaps(self):
        native = parse_twitch_emotes("1:0-3", "PogU hi")
        em = match_words("PogU hi", self.table, native)
        self.assertEqual(em, [])

    def test_disabled(self):
        t = ThirdPartyEmotes(enabled=False)
        t.table = self.table
        self.assertEqual(t.match("PogU", []), [])


class AdapterTests(unittest.TestCase):
    def test_privmsg_carries_emotes(self):
        from adapters.twitch import TwitchAdapter
        from core.models import ChatEvent

        class Bus:
            def __init__(self):
                self.events: list[ChatEvent] = []

            async def publish_chat(self, e):
                self.events.append(e)

        class Metrics:
            def record_message(self):
                pass

        bus = Bus()
        a = TwitchAdapter({"twitch": {"channel": "somechan", "third_party_emotes": True}}, bus, Metrics())
        a.emotes3p.room_id = "123"           # pretend the table is already loaded
        a.emotes3p._loaded_at = 1e18
        a.emotes3p.table = _seventv([{"id": "s1", "name": "PogU",
            "data": {"animated": True, "host": {"url": "//cdn.7tv.app/emote/s1"}}}])

        class W:
            def write(self, b):
                pass

            async def drain(self):
                pass

        line = ("@badges=;color=#1E90FF;display-name=Viewer;emotes=25:0-4;id=abc;mod=0;room-id=123;"
                "subscriber=0;user-id=42 :viewer!viewer@viewer.tmi.twitch.tv PRIVMSG #somechan :\x01ACTION Kappa PogU\x01")
        asyncio.run(a._on_line(W(), line))
        ev = bus.events[0]
        self.assertEqual(ev.message, "Kappa PogU")
        self.assertEqual([(e["provider"], e["start"], e["end"]) for e in ev.emotes],
                         [("twitch", 0, 4), ("7tv", 6, 9)])
        self.assertTrue(ev.emotes[1]["animated"])
        self.assertIn("emotes", ev.to_dict())


if __name__ == "__main__":
    unittest.main()
