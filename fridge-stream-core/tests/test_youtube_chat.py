"""YouTube chat: emoji / custom emoji in InnerTube runs, and reactions aimed at YouTube
handles ("@Name"). Run from fridge-stream-core:

    python -m unittest tests.test_youtube_chat -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.youtube import runs_to_text_and_emotes  # noqa: E402
from core.models import Platform  # noqa: E402
from core.reactions import target_key  # noqa: E402
from tests.test_reactions import FakeWS, Harness, entry, ev, run  # noqa: E402

HEART = {"emoji": {"emojiId": "UCkszU2WH9gy1mb0dV-11UJg/G8AfY6yWGuKuhL0PlbiA2AE",
                   "shortcuts": [":face-red-heart-shape:"], "isCustomEmoji": True,
                   "image": {"thumbnails": [{"url": "https://yt3.ggpht.com/heart=w24-h24", "width": 24},
                                            {"url": "https://yt3.ggpht.com/heart=w48-h48", "width": 48}]}}}
BREAD = {"emoji": {"emojiId": "🥖", "shortcuts": [":baguette_bread:"],
                   "image": {"thumbnails": [{"url": "https://www.youtube.com/s/gaming/emoji/x/emoji_u1f956.svg"}]}}}
TOMATO = {"emoji": {"emojiId": "🍅", "shortcuts": [":tomato:"]}}


class RunsTests(unittest.TestCase):
    def test_standard_emoji_become_characters(self):
        text, emotes = runs_to_text_and_emotes({"runs": [BREAD, BREAD, {"text": " yum "}, TOMATO]})
        self.assertEqual(text, "🥖🥖 yum 🍅")
        self.assertEqual(emotes, [])

    def test_custom_emoji_get_ranges(self):
        text, emotes = runs_to_text_and_emotes({"runs": [{"text": "hi "}, HEART, HEART]})
        self.assertEqual(text, "hi :face-red-heart-shape::face-red-heart-shape:")
        self.assertEqual(len(emotes), 2)
        e = emotes[1]
        self.assertEqual(text[e["start"]:e["end"] + 1], ":face-red-heart-shape:")
        self.assertEqual(e["url"], "https://yt3.ggpht.com/heart=w48-h48")   # largest
        self.assertEqual(e["provider"], "youtube")

    def test_code_points(self):
        text, emotes = runs_to_text_and_emotes({"runs": [TOMATO, {"text": " "}, HEART]})
        e = emotes[0]
        self.assertEqual(e["start"], 2)      # 🍅 is one code point
        self.assertEqual(text[e["start"]:e["end"] + 1], ":face-red-heart-shape:")

    def test_simple_text(self):
        self.assertEqual(runs_to_text_and_emotes({"simpleText": "hello"}), ("hello", []))


class HandleTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self.tmp.name))
        self.ws = FakeWS()
        run(self.h.eng.on_client_message(self.ws, {"type": "hello", "data": {"client": "stream_rooms", "protocol": 1}}))
        run(self.h.eng.on_client_message(self.ws, {"type": "room_state", "data": {
            "room": "hall", "targets": [{"id": "screen"}], "guests": [],
            "seated": ["@malonecara", "alice"]}}))
        self.h.set_entries(entry())
        self.ws.sent.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def fire(self, text, user="@SensokaFlaVR"):
        self.ws.sent.clear()
        self.h.replies.clear()
        run(self.h.eng.handle_chat(ev(text, user=user, platform=Platform.YOUTUBE)))
        return self.ws.sent[-1]["data"].get("target") if self.ws.sent else None

    def test_target_key_ignores_at(self):
        self.assertEqual(target_key("@MaloneCara"), target_key("malonecara"))

    def test_youtube_handles_are_targetable(self):
        for text in ("!tomato MaloneCara", "!tomato @MaloneCara", "🍅 @MaloneCara"):
            t = self.fire(text)
            self.assertIsNotNone(t, text)
            self.assertEqual(t["type"], "user")
            self.assertEqual(target_key(t["name"]), "malonecara")

    def test_reply_has_single_at(self):
        self.fire("!tomato nobody")
        self.assertTrue(self.h.replies)
        self.assertTrue(self.h.replies[-1].startswith("@SensokaFlaVR "), self.h.replies[-1])

    def test_opt_out_with_handle(self):
        run(self.h.eng.handle_chat(ev("!nothrow", user="@MaloneCara", platform=Platform.YOUTUBE)))
        self.assertIsNone(self.fire("!tomato MaloneCara"))
        self.assertIn("isn't taking reactions", self.h.replies[-1])


if __name__ == "__main__":
    unittest.main()
