"""Chat replies: a message sent with the platform's reply button carries who it answers.
Run from fridge-stream-core:

    python -m unittest tests.test_chat_replies -v
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.kick import KickAdapter, kick_reply_to  # noqa: E402
from adapters.twitch import TwitchAdapter, _parse_tags, strip_reply_mention, twitch_reply_to  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402


def run(coro):
    return asyncio.run(coro)        # (a fresh loop each time: other tests may have closed theirs)


class Rig:
    def __init__(self, cls, config=None):
        self.bus = EventBus()
        self.chat: list = []

        async def on_chat(e):
            self.chat.append(e)

        self.bus.on_chat(on_chat)
        self.adapter = cls(config or {}, self.bus, MetricsAggregator({}))


class KickReplies(unittest.TestCase):
    def test_metadata_becomes_reply_to(self):
        data = {"id": "m2", "content": "local is the future", "sender": {"id": 5, "username": "Bob", "slug": "bob"},
                "metadata": {"original_sender": {"id": 1, "username": "Sensoka_FlaVR"},
                             "original_message": {"id": "m1", "content": "cloud gaming is a scam"}}}
        self.assertEqual(kick_reply_to(data), {"user": "Sensoka_FlaVR", "message": "cloud gaming is a scam", "message_id": "m1"})
        self.assertIsNone(kick_reply_to({"id": "m3", "content": "plain"}))
        self.assertIsNone(kick_reply_to({"metadata": {"original_sender": {}}}))

    def test_event_carries_it(self):
        rig = Rig(KickAdapter, {"kick": {"channel": "fridge", "avatars": False}})
        run(rig.adapter._on_chat_message({"id": "m2", "content": "local is the future",
                                          "sender": {"id": 5, "username": "Bob", "slug": "bob", "profile_pic": ""},
                                          "metadata": {"original_sender": {"id": 1, "username": "Sensoka_FlaVR"},
                                                       "original_message": {"id": "m1", "content": "cloud gaming is a scam"}}}))
        e = rig.chat[0]
        self.assertEqual(e.reply_to["user"], "Sensoka_FlaVR")
        self.assertEqual(e.message, "local is the future")
        self.assertEqual(e.to_dict()["reply_to"]["message_id"], "m1")


class TwitchReplies(unittest.TestCase):
    def test_tags_and_unescaping(self):
        tags = _parse_tags("reply-parent-msg-id=abc;reply-parent-display-name=Sen;reply-parent-user-login=sen;"
                           "reply-parent-msg-body=hello\\sthere\\:\\sok;display-name=Amy")
        self.assertEqual(tags["reply-parent-msg-body"], "hello there; ok")
        self.assertEqual(twitch_reply_to(tags), {"user": "Sen", "message": "hello there; ok", "message_id": "abc"})
        self.assertIsNone(twitch_reply_to({"display-name": "Amy"}))

    def test_mention_prefix_dropped(self):
        r = {"user": "Sen", "message": "hi", "message_id": "abc"}
        self.assertEqual(strip_reply_mention("@Sen same here", r), "same here")
        self.assertEqual(strip_reply_mention("@someoneelse hi", r), "@someoneelse hi")
        self.assertEqual(strip_reply_mention("no mention", None), "no mention")

    def test_privmsg_line(self):
        rig = Rig(TwitchAdapter, {"twitch": {"channel": "fridge", "third_party_emotes": False}})
        line = ("@display-name=Amy;user-id=3;reply-parent-msg-id=abc;reply-parent-display-name=Sen;"
                "reply-parent-user-login=sen;reply-parent-msg-body=cloud\\sgaming :amy!amy@amy.tmi.twitch.tv PRIVMSG #fridge :@Sen local is the future")
        run(rig.adapter._on_line(None, line))
        e = rig.chat[0]
        self.assertEqual(e.reply_to, {"user": "Sen", "message": "cloud gaming", "message_id": "abc"})
        self.assertEqual(e.message, "local is the future")
        plain = "@display-name=Amy;user-id=3 :amy!amy@amy.tmi.twitch.tv PRIVMSG #fridge :hi"
        run(rig.adapter._on_line(None, plain))
        self.assertIsNone(rig.chat[1].reply_to)

    def test_emotes_move_with_dropped_mention(self):
        rig = Rig(TwitchAdapter, {"twitch": {"channel": "fridge", "third_party_emotes": False}})
        # "@daxtcrowleyvt " is 15 characters; Twitch counts emote positions from the "@"
        text = "@daxtcrowleyvt grimmi14Clap grimmi14Clap"
        line = ("@display-name=Hes;user-id=4;emotes=123:15-26,28-39;reply-parent-msg-id=abc;"
                "reply-parent-display-name=daxtcrowleyvt;reply-parent-user-login=daxtcrowleyvt;"
                "reply-parent-msg-body=Pippa :hes!hes@hes.tmi.twitch.tv PRIVMSG #fridge :" + text)
        run(rig.adapter._on_line(None, line))
        e = rig.chat[0]
        self.assertEqual(e.message, "grimmi14Clap grimmi14Clap")
        self.assertEqual([(m["start"], m["end"]) for m in e.emotes], [(0, 11), (13, 24)])
        for m in e.emotes:
            self.assertEqual(e.message[m["start"]:m["end"] + 1], "grimmi14Clap")


if __name__ == "__main__":
    unittest.main()
