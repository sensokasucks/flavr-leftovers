"""Raids, cheers (Bits) and Kick hosts / Kicks from the chat connections → overlay alerts.
Run from fridge-stream-core:

    python -m unittest tests.test_platform_events -v
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

from adapters.kick import KickAdapter, kick_event_alert  # noqa: E402
from adapters.twitch import TwitchAdapter, cheer_bits, usernotice_alert  # noqa: E402
from core.alerts import build_alert  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Rig:
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


class TwitchRaidAndBits(unittest.TestCase):
    def test_raid_notice(self):
        r = usernotice_alert({"msg-id": "raid", "login": "big", "display-name": "Big", "user-id": "7",
                              "msg-param-login": "big", "msg-param-displayName": "Big",
                              "msg-param-viewerCount": "321"})
        self.assertEqual((r["kind"], r["username"], r["display_name"], r["viewers"]), ("raid", "big", "Big", 321))

    def test_raid_line_alerts(self):
        rig = Rig(TwitchAdapter, {"twitch": {"channel": "fridge", "third_party_emotes": False}})
        line = ("@display-name=Big;login=big;msg-id=raid;msg-param-displayName=Big;msg-param-login=big;"
                "msg-param-viewerCount=55;user-id=7 :tmi.twitch.tv USERNOTICE #fridge")
        run(rig.adapter._on_line(None, line))
        self.assertEqual([(a["kind"], a["viewers"], a["headline"]) for a in rig.alerts],
                         [("raid", 55, "Big raided with 55 viewers!")])

    def test_cheer_is_paid_chat(self):
        self.assertEqual((cheer_bits({"bits": "250"}), cheer_bits({}), cheer_bits({"bits": "x"})), (250, 0, 0))
        rig = Rig(TwitchAdapter, {"twitch": {"channel": "fridge", "third_party_emotes": False}})
        line = "@bits=100;display-name=Amy;user-id=3 :amy!amy@amy.tmi.twitch.tv PRIVMSG #fridge :Cheer100 hype"
        run(rig.adapter._on_line(None, line))
        e = rig.chat[0]
        self.assertEqual((e.is_paid, e.paid_amount, e.paid_currency), (True, 100.0, "bits"))
        plain = "@display-name=Amy;user-id=3 :amy!amy@amy.tmi.twitch.tv PRIVMSG #fridge :hi"
        run(rig.adapter._on_line(None, plain))
        self.assertFalse(rig.chat[1].is_paid)


class KickHostsAndKicks(unittest.TestCase):
    def test_host_with_viewers_is_a_raid(self):
        a = kick_event_alert("App\\Events\\StreamHostEvent",
                             {"host_username": "Raider", "number_viewers": 42, "optional_message": "hi"})
        self.assertEqual((a["kind"], a["viewers"], a["message"]), ("raid", 42, "hi"))
        h = kick_event_alert("App\\Events\\StreamHostEvent", {"host_username": "Pal", "number_viewers": 0})
        self.assertEqual(h["kind"], "host")
        self.assertIsNone(kick_event_alert("App\\Events\\StreamHostEvent", {}))

    def test_kicks(self):
        a = kick_event_alert("KicksGifted", {"message": "gg", "sender": {"id": 5, "username": "Tipper"},
                                             "gift": {"amount": 100, "name": "Rage Quit"}})
        self.assertEqual((a["kind"], a["amount"], a["currency"], a["message"], a["user_id"]),
                         ("donation", 100.0, "KICKs", "gg", "5"))
        self.assertIsNone(kick_event_alert("KicksGifted", {"sender": {"username": "Tipper"}, "gift": {}}))
        self.assertEqual(build_alert(kind="donation", username="Tipper", amount=100, currency="KICKs")["headline"],
                         "Tipper donated 100 KICKs!")

    def test_pusher_frames_alert_once(self):
        rig = Rig(KickAdapter, {"kick": {"channel_slug": "fridge", "chatroom_id": 1, "avatars": False}})
        frame = json.dumps({"event": "App\\Events\\StreamHostEvent", "channel": "chatrooms.1.v2",
                            "data": json.dumps({"host_username": "Raider", "number_viewers": 12})})
        run(rig.adapter._handle_raw(frame))
        run(rig.adapter._handle_raw(frame))       # the same event on the second chatroom channel
        tip = json.dumps({"event": "KicksGifted", "channel": "channel_9",
                          "data": json.dumps({"sender": {"username": "Tipper"}, "gift": {"amount": 50}})})
        run(rig.adapter._handle_raw(tip))
        self.assertEqual([(a["kind"], a["platform"]) for a in rig.alerts], [("raid", "kick"), ("donation", "kick")])


if __name__ == "__main__":
    unittest.main()
