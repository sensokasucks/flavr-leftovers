"""YouTube replies to Super Chats (InnerTube): the reply's chip names who it answers and
shares a reply-thread id with the Super Chat's Reply button, so Core quotes the exact
Super Chat. Shapes copied from a real capture (data/youtube_new_fields.jsonl), names made up.
Run from fridge-stream-core:

    python -m unittest tests.test_youtube_replies -v
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.youtube import YouTubeAdapter, reply_chip, reply_thread_id, superchat_thread_id  # noqa: E402
from adapters.youtube_capture import FieldScout  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402

THREAD = "UgzUI-6MYiwbVMiGQ794AaABDqgB15-3kAI"


def params(thread: str) -> str:
    # protobuf-ish bytes around the thread id, base64 with url-escaped padding, as YouTube sends
    raw = b"\x82\x09\xad\x03\x0a\x23" + thread.encode() + b"\x12\x56\x0a\x29" + b"\x00" * 9
    return base64.b64encode(raw).decode().replace("=", "%3D")


def panel_button(thread: str, **extra) -> dict:
    vm = {"onTap": {"innertubeCommand": {"showEngagementPanelEndpoint": {
        "identifier": {"surface": "ENGAGEMENT_PANEL_SURFACE_LIVE_CHAT", "tag": "PAreply_thread"},
        "globalConfiguration": {"params": params(thread)}}}}}
    vm.update(extra)
    return vm


def superchat(mid: str, who: str, text: str, thread: str) -> dict:
    return {"addChatItemAction": {"item": {"liveChatPaidMessageRenderer": {
        "id": mid, "authorName": {"simpleText": who}, "authorExternalChannelId": "UC" + who,
        "purchaseAmountText": {"simpleText": "$5.00"}, "message": {"runs": [{"text": text}]},
        "replyButton": {"pdgReplyButtonViewModel": {"replyButton": {"buttonViewModel": panel_button(
            thread, iconName="CHAT", accessibilityText="Reply")}}}}}}}


def text_msg(mid: str, who: str, text: str, chips: list) -> dict:
    return {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
        "id": mid, "authorName": {"simpleText": who}, "authorExternalChannelId": "UC" + who,
        "message": {"runs": [{"text": text}]}, "beforeContentButtons": chips}}}}


REPLY_CHIP = {"buttonViewModel": panel_button(THREAD, iconName="MESSAGE", title="@postal_otter", iconTrailing=True)}
RANK_CHIP = {"buttonViewModel": {"iconName": "CROWN_FILLED", "title": "#1", "onTap": {"innertubeCommand": {
    "showEngagementPanelEndpoint": {"identifier": {"tag": "PAlive_viewer_leaderboard"},
                                    "globalConfiguration": {"params": "wgovGAAi"}}}}}}


def run(coro):
    return asyncio.run(coro)


class Parsing(unittest.TestCase):
    def test_thread_ids_match(self):
        sc = superchat("s1", "@postal_otter", "x", THREAD)["addChatItemAction"]["item"]["liveChatPaidMessageRenderer"]
        self.assertEqual(superchat_thread_id(sc), THREAD)
        self.assertEqual(reply_thread_id(REPLY_CHIP["buttonViewModel"]), THREAD)
        self.assertEqual(reply_thread_id(RANK_CHIP["buttonViewModel"]), "")

    def test_chip(self):
        self.assertEqual(reply_chip({"beforeContentButtons": [RANK_CHIP, REPLY_CHIP]}),
                         {"user": "@postal_otter", "thread": THREAD})
        self.assertIsNone(reply_chip({"beforeContentButtons": [RANK_CHIP]}))
        self.assertIsNone(reply_chip({}))
        bad = {"buttonViewModel": dict(REPLY_CHIP["buttonViewModel"])}
        bad["buttonViewModel"]["onTap"] = {"innertubeCommand": {"showEngagementPanelEndpoint": {
            "identifier": {"tag": "PAreply_thread"}, "globalConfiguration": {"params": "%%%not-base64"}}}}
        self.assertEqual(reply_chip({"beforeContentButtons": [bad]}), {"user": "@postal_otter", "thread": ""})


class Adapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "new.jsonl"
        bus = EventBus()
        self.chat: list = []

        async def on_chat(e):
            self.chat.append(e)

        bus.on_chat(on_chat)
        self.yt = YouTubeAdapter({"youtube": {"video_id": "abc"}}, bus, MetricsAggregator({}))
        self.yt.scout = FieldScout(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reply_quotes_the_super_chat(self):
        run(self.yt._on_innertube_action(superchat("s1", "@postal_otter", "she should play Mario Sunshine", THREAD)))
        run(self.yt._on_innertube_action(text_msg("r1", "@noise_ferret", "She'll love the Pinata people", [REPLY_CHIP])))
        sc, reply = self.chat
        self.assertTrue(sc.is_paid)
        self.assertIsNone(sc.reply_to)
        self.assertEqual(reply.reply_to, {"user": "@postal_otter", "message": "she should play Mario Sunshine", "message_id": "s1"})
        self.assertEqual(reply.to_dict()["reply_to"]["message_id"], "s1")
        self.assertEqual(reply.message, "She'll love the Pinata people")

    def test_reply_to_an_unseen_super_chat_still_names_them(self):
        run(self.yt._on_innertube_action(text_msg("r2", "@noise_ferret", "@postal_otter same", [REPLY_CHIP])))
        self.assertEqual(self.chat[0].reply_to, {"user": "@postal_otter", "message": "", "message_id": ""})
        self.assertEqual(self.chat[0].message, "same")     # the leading @name is dropped

    def test_rank_chip_is_not_a_reply_and_known_data_is_quiet(self):
        run(self.yt._on_innertube_action(text_msg("t1", "@crowned", "first!", [RANK_CHIP])))
        self.assertIsNone(self.chat[0].reply_to)
        self.assertFalse(self.path.exists())

    def test_unknown_chip_is_noted(self):
        odd = {"buttonViewModel": {"iconName": "SPARKLE", "title": "new thing"}}
        run(self.yt._on_innertube_action(text_msg("t2", "@someone", "hi", [odd])))
        lines = [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["new"] for x in lines], ["chip:SPARKLE"])
        self.assertEqual(self.chat[0].message, "hi")


if __name__ == "__main__":
    unittest.main()
