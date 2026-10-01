"""Sub / resub / gift detection in the chat adapters → overlay alerts. Run from
fridge-stream-core:

    python -m unittest tests.test_sub_alerts -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.kick import KickAdapter, kick_sub_alert  # noqa: E402
from adapters.twitch import TwitchAdapter, usernotice_alert  # noqa: E402
from adapters.youtube import YouTubeAdapter, official_member_alert  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Rig:
    """An adapter wired to a bus that records alerts and chat."""

    def __init__(self, cls, config=None):
        self.bus = EventBus()
        self.alerts: list[dict] = []
        self.chat: list = []

        async def on_alert(p):
            self.alerts.append(p)

        async def on_chat(e):
            self.chat.append(e)

        self.bus.on_alert(on_alert)
        self.bus.on_chat(on_chat)
        self.adapter = cls(config or {}, self.bus, MetricsAggregator({}))


class TwitchTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(usernotice_alert({"msg-id": "sub", "login": "bob", "display-name": "Bob"})["kind"],
                         "subscribe")
        r = usernotice_alert({"msg-id": "resub", "login": "bob", "msg-param-cumulative-months": "7"}, "hi")
        self.assertEqual((r["kind"], r["months"], r["message"]), ("resub", 7, "hi"))
        g = usernotice_alert({"msg-id": "subgift", "login": "amy"})
        self.assertEqual((g["kind"], g["qty"]), ("gift", 1))
        b = usernotice_alert({"msg-id": "submysterygift", "login": "amy", "msg-param-mass-gift-count": "10"})
        self.assertEqual((b["kind"], b["qty"]), ("gift", 10))
        self.assertIsNone(usernotice_alert({"msg-id": "raid", "login": "x"}))

    def test_gift_bomb_recipients_do_not_alert(self):
        self.assertIsNone(usernotice_alert({"msg-id": "subgift", "login": "amy",
                                            "msg-param-community-gift-id": "123"}))

    def test_irc_line(self):
        rig = Rig(TwitchAdapter, {"twitch": {"channel": "fridge", "third_party_emotes": False}})
        line = ("@badges=;display-name=Bob;login=bob;msg-id=resub;msg-param-cumulative-months=3 "
                ":tmi.twitch.tv USERNOTICE #fridge :still here")
        run(rig.adapter._on_line(None, line))
        self.assertEqual(len(rig.alerts), 1)
        a = rig.alerts[0]
        self.assertEqual((a["kind"], a["platform"], a["username"], a["months"], a["message"]),
                         ("resub", "twitch", "bob", 3, "still here"))
        self.assertEqual(a["source"], "platform")
        self.assertEqual(rig.chat, [])


class YouTubeTests(unittest.TestCase):
    def test_official(self):
        author = {"displayName": "Ann", "channelId": "UC1"}
        self.assertEqual(official_member_alert({"type": "newSponsorEvent"}, author)[1]["kind"], "subscribe")
        _, r = official_member_alert({"type": "memberMilestoneChatEvent",
                                      "memberMilestoneChatDetails": {"memberMonth": 4, "userComment": "yo"}},
                                     author)
        self.assertEqual((r["kind"], r["months"], r["message"]), ("resub", 4, "yo"))
        _, g = official_member_alert({"type": "membershipGiftingEvent",
                                      "membershipGiftingDetails": {"giftMembershipsCount": 5}}, author)
        self.assertEqual((g["kind"], g["qty"]), ("gift", 5))
        self.assertEqual(official_member_alert({"type": "giftMembershipReceivedEvent"}, author), (True, None))
        self.assertEqual(official_member_alert({"type": "textMessageEvent"}, author), (False, None))

    def test_official_new_member_is_not_chat(self):
        rig = Rig(YouTubeAdapter)
        run(rig.adapter._on_official_item({
            "id": "m1",
            "snippet": {"type": "newSponsorEvent", "displayMessage": "Ann is a new member"},
            "authorDetails": {"displayName": "Ann", "channelId": "UC1"},
        }))
        self.assertEqual([a["kind"] for a in rig.alerts], ["subscribe"])
        self.assertEqual(rig.chat, [])

    def test_innertube_new_member(self):
        rig = Rig(YouTubeAdapter)
        run(rig.adapter._on_innertube_action({"addChatItemAction": {"item": {
            "liveChatMembershipItemRenderer": {
                "id": "a", "authorName": {"simpleText": "Ann"}, "authorExternalChannelId": "UC1",
                "headerSubtext": {"runs": [{"text": "Welcome to Fridge!"}]},
            }}}}))
        self.assertEqual([a["kind"] for a in rig.alerts], ["subscribe"])
        self.assertEqual(rig.chat, [])

    def test_innertube_milestone_keeps_chat(self):
        rig = Rig(YouTubeAdapter)
        run(rig.adapter._on_innertube_action({"addChatItemAction": {"item": {
            "liveChatMembershipItemRenderer": {
                "id": "b", "authorName": {"simpleText": "Ann"},
                "headerPrimaryText": {"runs": [{"text": "Member for "}, {"text": "1"}, {"text": " year"}]},
                "message": {"runs": [{"text": "love it"}]},
            }}}}))
        a = rig.alerts[0]
        self.assertEqual((a["kind"], a["months"], a["message"]), ("resub", 12, "love it"))
        self.assertEqual([e.message for e in rig.chat], ["love it"])

    def test_innertube_gift(self):
        rig = Rig(YouTubeAdapter)
        run(rig.adapter._on_innertube_action({"addChatItemAction": {"item": {
            "liveChatSponsorshipsGiftPurchaseAnnouncementRenderer": {
                "id": "g", "authorExternalChannelId": "UC2",
                "header": {"liveChatSponsorshipsHeaderRenderer": {
                    "authorName": {"simpleText": "Gus"},
                    "primaryText": {"runs": [{"text": "Gifted "}, {"text": "20"}, {"text": " memberships"}]},
                }},
            }}}}))
        a = rig.alerts[0]
        self.assertEqual((a["kind"], a["qty"], a["display_name"]), ("gift", 20, "Gus"))


class KickTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(kick_sub_alert("App\\Events\\SubscriptionEvent", {"username": "z", "months": 1})["kind"],
                         "subscribe")
        r = kick_sub_alert("App\\Events\\SubscriptionEvent", {"username": "z", "months": 6})
        self.assertEqual((r["kind"], r["months"]), ("resub", 6))
        g = kick_sub_alert("App\\Events\\GiftedSubscriptionsEvent",
                           {"gifter_username": "g", "gifted_usernames": ["a", "b", "c"]})
        self.assertEqual((g["kind"], g["qty"], g["username"]), ("gift", 3, "g"))

    def test_pusher_frame_and_duplicate_channel(self):
        rig = Rig(KickAdapter)
        frame = json.dumps({"event": "App\\Events\\GiftedSubscriptionsEvent",
                            "channel": "chatrooms.1.v2",
                            "data": json.dumps({"gifter_username": "g", "gifted_usernames": ["a", "b"]})})
        run(rig.adapter._handle_raw(frame))
        run(rig.adapter._handle_raw(frame.replace("chatrooms.1.v2", "chatrooms.1")))
        self.assertEqual([(a["kind"], a["qty"], a["platform"]) for a in rig.alerts], [("gift", 2, "kick")])


if __name__ == "__main__":
    unittest.main()
