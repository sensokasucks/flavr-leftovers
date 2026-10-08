"""Twitch channel-point message styles, paid fields on the chat payload, and the note Core
keeps of YouTube chat data it doesn't read yet. Run from fridge-stream-core:

    python -m unittest tests.test_chat_highlights -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.twitch import TwitchAdapter, twitch_highlight  # noqa: E402
from adapters.youtube import YouTubeAdapter  # noqa: E402
from adapters.youtube_capture import MAX_LINES, FieldScout  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def rig(cls, config):
    bus = EventBus()
    chat: list = []

    async def on_chat(e):
        chat.append(e)

    bus.on_chat(on_chat)
    return cls(config, bus, MetricsAggregator({})), chat


class TwitchHighlights(unittest.TestCase):
    def test_msg_id_values(self):
        self.assertEqual(twitch_highlight({"msg-id": "highlighted-message"}), "highlighted")
        self.assertEqual(twitch_highlight({"msg-id": "gigantified-emote-message"}), "gigantified")
        self.assertEqual(twitch_highlight({"msg-id": "animated-message"}), "animated")
        self.assertIsNone(twitch_highlight({"msg-id": "something-new"}))
        self.assertIsNone(twitch_highlight({}))

    def test_privmsg_line(self):
        adapter, chat = rig(TwitchAdapter, {"twitch": {"channel": "fridge", "third_party_emotes": False}})
        line = ("@display-name=jon_aka_proto;user-id=7;msg-id=highlighted-message "
                ":jon!jon@jon.tmi.twitch.tv PRIVMSG #fridge :Pippa would be the kind of person")
        run(adapter._on_line(None, line))
        run(adapter._on_line(None, "@display-name=Amy;user-id=3 :amy!amy@amy.tmi.twitch.tv PRIVMSG #fridge :hi"))
        self.assertEqual(chat[0].highlight, "highlighted")
        self.assertEqual(chat[0].to_dict()["highlight"], "highlighted")
        self.assertIsNone(chat[1].highlight)


class ChatPayload(unittest.TestCase):
    def test_payload_carries_paid_and_highlight(self):
        from main import StreamCore
        from core.models import ChatEvent, ChatUser, Platform

        core = StreamCore({})
        sent: list = []

        class WS:
            async def broadcast(self, payload):
                sent.append(payload)

        core.state.ws_manager = WS()
        user = ChatUser(platform=Platform.TWITCH, id="7", username="jon", display_name="jon")
        ev = ChatEvent(platform=Platform.TWITCH, user=user, message="hello", highlight="highlighted",
                       is_paid=True, paid_amount=100.0, paid_currency="bits")
        try:
            run(core._on_chat(ev))
        except Exception:
            pass        # later steps (credits, commands) don't matter here
        chat = [p["data"] for p in sent if p.get("type") == "chat"]
        self.assertTrue(chat, "no chat payload broadcast")
        d = chat[0]
        self.assertEqual(d["highlight"], "highlighted")
        self.assertTrue(d["is_paid"])
        self.assertEqual(d["paid_amount"], 100.0)
        self.assertEqual(d["paid_currency"], "bits")


class YouTubeFieldScout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "youtube_new_fields.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self):
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines()]

    def test_known_data_is_quiet(self):
        scout = FieldScout(self.path)
        scout.check_action({"addChatItemAction": {}, "clickTrackingParams": "x"})
        scout.check_item({"liveChatTextMessageRenderer": {"id": "1", "message": {}, "authorName": {}}})
        self.assertEqual(self.lines(), [])

    def test_new_things_saved_once(self):
        scout = FieldScout(self.path)
        item = {"liveChatTextMessageRenderer": {"id": "1", "message": {}, "beforeContentButtons": [{"x": 1}]}}
        scout.check_item(item)
        scout.check_item(item)
        scout.check_item({"liveChatSuperChatReplyRenderer": {"id": "2"}})
        scout.check_action({"addSuperChatReplyAction": {}})
        got = [x["new"] for x in self.lines()]
        self.assertEqual(got, ["field:liveChatTextMessageRenderer.beforeContentButtons",
                               "item:liveChatSuperChatReplyRenderer", "action:addSuperChatReplyAction"])
        self.assertEqual(self.lines()[0]["sample"], item)

    def test_file_is_capped(self):
        scout = FieldScout(self.path)
        for i in range(MAX_LINES + 20):
            scout.check_action({f"newAction{i}": {}})
        self.assertEqual(len(self.lines()), MAX_LINES)

    def test_adapter_reports_and_still_emits(self):
        adapter, chat = rig(YouTubeAdapter, {"youtube": {"video_id": "abc"}})
        adapter.scout = FieldScout(self.path)
        action = {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
            "id": "m1", "authorName": {"simpleText": "@CyberKnightProbably"}, "authorExternalChannelId": "UC1",
            "message": {"runs": [{"text": "Gradius 5? God Of War?"}]},
            "replyToSuperChat": {"author": "@weirdsoupcartoonsyeah"}}}}}
        run(adapter._on_innertube_action(action))
        self.assertEqual(chat[0].message, "Gradius 5? God Of War?")
        self.assertEqual([x["new"] for x in self.lines()], ["field:liveChatTextMessageRenderer.replyToSuperChat"])


if __name__ == "__main__":
    unittest.main()
