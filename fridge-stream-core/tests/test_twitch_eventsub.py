"""Twitch EventSub paid events (bits power-ups and celebrations, charity, Hype Trains):
reading each event, the WebSocket session against a fake Twitch, and how Core lists and
shows them. Nothing here touches the network. Run from fridge-stream-core:

    python -m unittest tests.test_twitch_eventsub -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import adapters.twitch_eventsub as es  # noqa: E402
from adapters.twitch_auth import PAID_SCOPES, SCOPES  # noqa: E402
from core.alerts import build_alert  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.store import Store  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def bits_event(kind="power_up", bits=300, ptype="celebration", emote=None, text=""):
    ev = {"user_id": "11", "user_login": "amy", "user_name": "Amy", "broadcaster_user_id": "99",
          "bits": bits, "type": kind, "message": {"text": text, "fragments": []} if text else None,
          "power_up": None, "custom_power_up": None}
    if kind == "power_up":
        ev["power_up"] = {"type": ptype, "emote": {"id": "1", "name": emote} if emote else None,
                          "message_effect_id": None}
    if kind == "custom_power_up":
        ev["custom_power_up"] = {"title": "Spin the wheel", "reward_id": "r1"}
    return ev


class Reading(unittest.TestCase):
    def test_cheers_stay_with_chat(self):
        self.assertIsNone(es.bits_use_alert(bits_event(kind="cheer", text="cheer100 hi")))

    def test_power_ups(self):
        c = es.bits_use_alert(bits_event())
        self.assertEqual((c["kind"], c["amount"], c["currency"], c["item"], c["username"], c["user_id"]),
                         ("celebration", 300.0, "bits", "On-screen celebration", "amy", "11"))
        g = es.bits_use_alert(bits_event(bits=50, ptype="gigantify_an_emote", emote="Kappa", text="Kappa"))
        self.assertEqual((g["kind"], g["item"], g["message"]), ("powerup", "Gigantified Kappa", "Kappa"))
        m = es.bits_use_alert(bits_event(bits=30, ptype="message_effect", text="wow"))
        self.assertEqual((m["kind"], m["item"]), ("powerup", "Message effect"))
        cu = es.bits_use_alert(bits_event(kind="custom_power_up", bits=500))
        self.assertEqual((cu["kind"], cu["item"], cu["amount"]), ("powerup", "Spin the wheel", 500.0))

    def test_charity(self):
        a = es.charity_alert({"user_id": "5", "user_login": "bo", "user_name": "Bo", "charity_name": "Direct Relief",
                              "amount": {"value": 550, "decimal_places": 2, "currency": "USD"}})
        self.assertEqual((a["kind"], a["amount"], a["currency"], a["item"]), ("charity", 5.5, "USD", "Direct Relief"))
        y = es.charity_alert({"user_login": "yu", "amount": {"value": 1000, "decimal_places": 0, "currency": "JPY"}})
        self.assertEqual((y["amount"], y["currency"]), (1000, "JPY"))

    def test_hype_train(self):
        a = es.hype_train_alert({
            "broadcaster_user_id": "99", "broadcaster_user_login": "fridge", "broadcaster_user_name": "Fridge",
            "level": 4, "total": 13000, "type": "golden_kappa", "is_shared_train": False,
            "top_contributions": [{"user_name": "Amy", "type": "bits", "total": 5000},
                                  {"user_name": "Bo", "type": "subscription", "total": 1500}]})
        self.assertEqual((a["kind"], a["level"], a["item"], a["username"]),
                         ("hypetrain", 4, "Golden Kappa Train", "fridge"))
        self.assertEqual(a["message"], "Top: Amy (5,000 bits), Bo (subs)")
        alert = build_alert(**{k: v for k, v in a.items() if k != "user_id"}, platform="twitch")
        self.assertEqual(alert["headline"], "Golden Kappa Train ended at level 4!")
        self.assertIn("hypetrain-alert", alert["css_classes"])

    def test_new_alert_kinds_borrow_a_picture(self):
        for kind, back in (("powerup", "bits"), ("celebration", "bits"), ("charity", "donation"),
                           ("hypetrain", "raid")):
            self.assertEqual(build_alert(kind=kind, platform="twitch")["falls_back"], back)
        self.assertEqual(build_alert(kind="powerup", platform="twitch", amount=100, currency="bits",
                                     item="Message effect", username="amy")["headline"],
                         "amy used Message effect (100 bits)!")

    def test_sign_in_asks_for_paid_scopes(self):
        for scope in PAID_SCOPES:
            self.assertIn(scope, SCOPES)


class FakeAuth:
    def __init__(self, login="fridge", scopes=None, connected=True):
        self.connected = connected
        self.login = login
        self.user_id = "99"
        self.client_id = "cid"
        self._scopes = list(SCOPES if scopes is None else scopes)
        self.invalidated = 0

    def status(self):
        return {"scopes": self._scopes}

    async def token(self):
        return "tok"

    def invalidate(self):
        self.invalidated += 1


class FakeWS:
    def __init__(self, messages, stop):
        self.messages = list(messages)
        self.stop = stop

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def recv(self):
        if not self.messages:
            self.stop.set()         # script done: the client ends its session and stops
            return json.dumps({"metadata": {"message_type": "session_keepalive"}, "payload": {}})
        return json.dumps(self.messages.pop(0))


def welcome(sid="s1"):
    return {"metadata": {"message_id": "w", "message_type": "session_welcome"},
            "payload": {"session": {"id": sid, "keepalive_timeout_seconds": 10}}}


def note(mid, stype, event):
    return {"metadata": {"message_id": mid, "message_type": "notification"},
            "payload": {"subscription": {"type": stype}, "event": event}}


class Session(unittest.TestCase):
    def client(self, auth, scripts, http_status=202):
        got, posts, urls = [], [], []

        async def on_alert(a):
            got.append(a)

        async def http(method, url, body, headers):
            posts.append(body)
            return http_status, {}

        c = es.EventSubClient(auth, "fridge", on_alert, http=http)

        def connect(url, **kw):
            urls.append(url)
            return FakeWS(scripts.pop(0) if scripts else [], c._stop)

        c._connect = connect
        return c, got, posts, urls

    def test_subscribes_and_turns_events_into_alerts(self):
        celebrate = note("n1", "channel.bits.use", bits_event())
        c, got, posts, urls = self.client(FakeAuth(), [[
            welcome(), celebrate, celebrate,                       # Twitch may send one twice
            note("n2", "channel.bits.use", bits_event(kind="cheer")),
            {"metadata": {"message_type": "session_reconnect"},
             "payload": {"session": {"reconnect_url": "wss://elsewhere"}}},
        ], [welcome("s2"), note("n3", "channel.charity_campaign.donate",
                                {"user_login": "bo", "charity_name": "X",
                                 "amount": {"value": 500, "decimal_places": 2, "currency": "EUR"}})]])

        async def go():
            await asyncio.wait_for(c._loop(), 5)

        run(go())
        self.assertEqual([p["type"] for p in posts],
                         ["channel.bits.use", "channel.charity_campaign.donate", "channel.hype_train.end"])
        self.assertEqual(posts[0]["condition"], {"broadcaster_user_id": "99"})
        self.assertEqual(posts[0]["transport"], {"method": "websocket", "session_id": "s1"})
        self.assertEqual(urls, [es.WS_URL, "wss://elsewhere"])   # no new subscriptions after a move
        self.assertEqual([(a["kind"], a["event_id"]) for a in got], [("celebration", "n1"), ("charity", "n3")])
        self.assertEqual(len(c.subscribed), 3)

    def test_wrong_account_or_old_sign_in_stays_off(self):
        c, _, posts, _ = self.client(FakeAuth(login="somebot"), [])
        self.assertIn("not fridge", c.why_not())
        c2, _, _, _ = self.client(FakeAuth(scopes=["user:read:chat", "user:write:chat"]), [])
        self.assertIn("Reconnect", c2.why_not())
        c3, _, _, _ = self.client(FakeAuth(connected=False), [])
        self.assertIn("Connect Twitch", c3.why_not())
        self.assertEqual(self.client(FakeAuth(), [])[0].why_not(), "")

    def test_only_allowed_scopes_are_subscribed(self):
        c, _, posts, _ = self.client(FakeAuth(scopes=["user:read:chat", "bits:read"]), [[welcome()]])
        run(asyncio.wait_for(c._loop(), 5))
        self.assertEqual([p["type"] for p in posts], ["channel.bits.use"])

    def test_bits_live_follows_the_client(self):
        self.assertFalse(es.bits_live())
        c, _, _, _ = self.client(FakeAuth(), [])
        es._current, c.live, c.subscribed = c, True, {"channel.bits.use"}
        try:
            self.assertTrue(es.bits_live())
        finally:
            es._current = None


class CoreLists(unittest.TestCase):
    def test_paid_list_and_no_double_power_ups(self):
        from main import StreamCore
        from core.red_flags import RedFlags

        core = StreamCore({})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core.store = Store(Path(tmp.name) / "t.db")
        core.red_flags = RedFlags(core.store, {})
        core.state.config = {}

        def alert(a, event_id):
            p = build_alert(**{k: v for k, v in a.items() if k not in ("user_id", "event_id")}, platform="twitch")
            return {**p, "source": "platform", "user_id": a.get("user_id", ""), "event_id": event_id}

        celebrate = es.bits_use_alert(bits_event())
        train = es.hype_train_alert({"broadcaster_user_login": "fridge", "level": 2,
                                     "top_contributions": [{"user_name": "Amy", "type": "bits", "total": 900}]})

        def powerup_line(mid):
            u = ChatUser(platform=Platform.TWITCH, id="11", username="amy")
            return ChatEvent(platform=Platform.TWITCH, user=u, message="Kappa", highlight="gigantified",
                             message_id=mid)

        async def go():
            await core._on_alert(alert(celebrate, "n1"))
            await core._on_alert(alert(celebrate, "n1"))       # same event again: listed once
            await core._on_alert(alert(train, "n2"))
            await core._note_paid_chat(powerup_line("c1"))     # no EventSub: chat lists the power-up
            fake = es.EventSubClient(FakeAuth(), "fridge", None)
            es._current, fake.live, fake.subscribed = fake, True, {"channel.bits.use"}
            try:
                await core._note_paid_chat(powerup_line("c2"))  # EventSub lists it (with bits) instead
            finally:
                es._current = None

        run(go())
        rows = run(core.paid.list({"group": "all"}))["rows"]
        got = [(r["kind"], r["amount"], r["currency"], r["item"], r["message"]) for r in rows]
        self.assertEqual(got, [
            ("celebration", 300.0, "bits", "On-screen celebration", ""),
            ("hypetrain", None, "", "Hype Train level 2", "Top: Amy (900 bits)"),
            ("powerup", None, "", "Gigantified emote", "Kappa"),
        ])


if __name__ == "__main__":
    unittest.main()
