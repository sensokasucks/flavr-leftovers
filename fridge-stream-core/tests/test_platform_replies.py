"""Core's replies posted into the real Kick / Twitch / YouTube chat, with the overlay as the
fallback (main.py _deliver_reply, adapters' can_send / send_message, adapters/youtube_auth.py).
Nothing here talks to a real platform: every request goes to a fake. Run from fridge-stream-core:

    python -m pytest tests/test_platform_replies.py -q
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters import kick as kick_mod  # noqa: E402
from adapters import youtube as youtube_mod  # noqa: E402
from adapters.base import echo_key  # noqa: E402
from adapters.kick import KickAdapter, _slug_key  # noqa: E402
from adapters.twitch import TwitchAdapter  # noqa: E402
from adapters.youtube import YouTubeAdapter  # noqa: E402
from adapters.youtube_auth import YouTubeAuth  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402
from core.models import ChatEvent, ChatReply, ChatUser, Platform  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def chat_event(platform, text, name="viewer"):
    user = ChatUser(platform=platform, id="1", username=name, display_name=name)
    return ChatEvent(platform=platform, user=user, message=text, message_id="m1")


class FakeKickAuth:
    """Stands in for adapters/kick_auth.KickAuth."""

    def __init__(self, connected=True, login="sensoka-FlaVR", scopes=("user:read", "chat:write"), ok=True):
        self.connected, self.login, self._scopes, self.ok = connected, login, list(scopes), ok
        self.sent: list = []

    def status(self):
        return {"scopes": self._scopes}

    async def send_chat(self, text, reply_to_message_id=""):
        self.sent.append((text, reply_to_message_id))
        return (True, "") if self.ok else (False, "Kick refused the message: nope")


class EchoTests(unittest.TestCase):
    def test_echo_key(self):
        self.assertEqual(echo_key("  Hello   World… "), "hello world")

    def test_own_echo_is_marked_once(self):
        a = KickAdapter({"kick": {"channel_slug": "fridge", "avatars": False}}, EventBus(), MetricsAggregator({}))
        a._remember_sent("!1 or !2 to vote for the mix name")
        e = chat_event(Platform.KICK, "!1 or !2 to vote for the mix name", "fridge")
        self.assertTrue(a._is_own_echo(e))
        # used up: the same words typed again later are an ordinary line
        self.assertFalse(a._is_own_echo(chat_event(Platform.KICK, "!1 or !2 to vote for the mix name")))

    def test_forget_after_failed_post(self):
        a = KickAdapter({"kick": {"channel_slug": "fridge", "avatars": False}}, EventBus(), MetricsAggregator({}))
        a._remember_sent("hello there")
        a._forget_sent("hello there")
        self.assertFalse(a._is_own_echo(chat_event(Platform.KICK, "hello there")))


class KickSendTests(unittest.TestCase):
    def setUp(self):
        self._orig = kick_mod.get_kick_auth
        self.addCleanup(lambda: setattr(kick_mod, "get_kick_auth", self._orig))

    def adapter(self, auth):
        kick_mod.get_kick_auth = lambda cfg=None: auth
        return KickAdapter({"kick": {"channel_slug": "sensoka-flavr", "avatars": False}}, EventBus(), MetricsAggregator({}))

    def test_slug_key(self):
        self.assertEqual(_slug_key("Sensoka_FlaVR"), "sensoka-flavr")
        self.assertEqual(_slug_key("kick.com/sensoka-flavr"), "sensoka-flavr")

    def test_can_send(self):
        self.assertEqual(self.adapter(FakeKickAuth()).can_send(), (True, ""))
        self.assertFalse(self.adapter(FakeKickAuth(connected=False)).can_send()[0])
        self.assertFalse(self.adapter(FakeKickAuth(scopes=["user:read"])).can_send()[0])
        ok, why = self.adapter(FakeKickAuth(login="someone_else")).can_send()
        self.assertFalse(ok)
        self.assertIn("someone_else", why)

    def test_send_posts_as_reply(self):
        auth = FakeKickAuth()
        a = self.adapter(auth)
        self.assertTrue(run(a.send_message("you have 50 points", reply_to_message_id="abc")))
        self.assertEqual(auth.sent, [("you have 50 points", "abc")])
        self.assertTrue(a._is_own_echo(chat_event(Platform.KICK, "you have 50 points")))

    def test_failed_send_keeps_reason(self):
        a = self.adapter(FakeKickAuth(ok=False))
        self.assertFalse(run(a.send_message("hi")))
        self.assertIn("nope", a.last_send_error)
        self.assertFalse(a._is_own_echo(chat_event(Platform.KICK, "hi")))


class FakeTwitchAuth:
    def __init__(self, scopes=("user:read:chat", "user:write:chat")):
        self.connected, self.login, self.user_id, self.client_id = True, "fridge", "42", "cid"
        self._scopes = list(scopes)
        self.invalidated = 0

    def status(self):
        return {"scopes": self._scopes}

    async def token(self):
        return "tok"

    def invalidate(self):
        self.invalidated += 1


class TwitchSendTests(unittest.TestCase):
    def adapter(self, answers, auth=None):
        a = TwitchAdapter({"twitch": {"channel": "fridge", "avatars": False, "third_party_emotes": False}},
                          EventBus(), MetricsAggregator({}))
        a.auth = auth or FakeTwitchAuth()
        a.calls = []

        async def helix(method, url, body, headers):
            a.calls.append((method, url, body))
            return answers.pop(0)

        a._helix = helix
        return a

    def test_sent_as_threaded_reply(self):
        a = self.adapter([(200, {"data": [{"message_id": "x", "is_sent": True}]})])
        self.assertEqual(a.can_send(), (True, ""))
        self.assertTrue(run(a.send_message("pong", reply_to_message_id="irc-id")))
        method, url, body = a.calls[0]
        self.assertEqual(body, {"broadcaster_id": "42", "sender_id": "42", "message": "pong",
                                "reply_parent_message_id": "irc-id"})

    def test_dropped_message_falls_back(self):
        a = self.adapter([(200, {"data": [{"is_sent": False, "drop_reason": {"message": "AutoMod held it"}}]})])
        self.assertFalse(run(a.send_message("pong")))
        self.assertIn("AutoMod", a.last_send_error)

    def test_401_refreshes_once(self):
        a = self.adapter([(401, {}), (200, {"data": [{"is_sent": True}]})])
        self.assertTrue(run(a.send_message("pong")))
        self.assertEqual(a.auth.invalidated, 1)

    def test_missing_scope(self):
        a = self.adapter([], FakeTwitchAuth(scopes=["user:read:chat"]))
        self.assertFalse(a.can_send()[0])

    def test_other_channel_looks_up_id(self):
        auth = FakeTwitchAuth()
        auth.login = "my_bot"
        a = self.adapter([(200, {"data": [{"id": "99"}]}), (200, {"data": [{"is_sent": True}]})], auth)
        self.assertTrue(run(a.send_message("pong")))
        self.assertEqual(a.calls[1][2]["broadcaster_id"], "99")


class FakeGoogle:
    """Answers YouTubeAuth's requests from a list of (status, body), recording each call."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    async def __call__(self, method, url, form, body, headers):
        self.calls.append((method, url, form, body))
        return self.answers.pop(0)


class YouTubeAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "youtube_token.json"

    def auth(self, answers):
        http = FakeGoogle(answers)
        return YouTubeAuth("id.apps.googleusercontent.com", "secret", path=self.path, http=http), http

    def test_needs_app_first(self):
        a = YouTubeAuth(path=self.path, http=FakeGoogle([]))
        self.assertIn("Client ID", run(a.start_login())["error"])

    def test_device_sign_in(self):
        a, http = self.auth([
            (200, {"device_code": "dc", "user_code": "ABC-DEF", "verification_url": "https://www.google.com/device",
                   "expires_in": 1800, "interval": 5}),
            (428, {"error": "authorization_pending"}),
            (200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                   "scope": "https://www.googleapis.com/auth/youtube"}),
            (200, {"items": [{"id": "UC1", "snippet": {"title": "Sen"}}]}),
        ])

        async def go():
            s = await a.start_login()
            a.cancel_login()                      # stop the background poll; poll by hand
            a._pending = {"device_code": "dc", "expires_at": a._now() + 100, "interval": 5}
            self.assertEqual(s["pending"]["user_code"], "ABC-DEF")
            self.assertFalse(await a.poll_once())
            self.assertTrue(await a.poll_once())

        run(go())
        st = a.status()
        self.assertTrue(st["connected"])
        self.assertEqual(st["channel_title"], "Sen")
        self.assertNotIn("at", str(st))           # never shows the token
        self.assertTrue(self.path.exists())

    def test_send_chat_and_chat_id(self):
        a, http = self.auth([
            (200, {"items": [{"liveStreamingDetails": {"activeLiveChatId": "LC"}}]}),
            (200, {"id": "msg"}),
        ])
        a._tok = {"access_token": "at", "refresh_token": "rt", "expires_at": a._now() + 3600,
                  "client_id": "id.apps.googleusercontent.com"}

        async def go():
            chat, why = await a.live_chat_id("vid")
            self.assertEqual((chat, why), ("LC", ""))
            self.assertEqual(await a.live_chat_id("vid"), ("LC", ""))   # remembered, no second call
            return await a.send_chat("x" * 300, chat)

        self.assertEqual(run(go()), (True, ""))
        sent = http.calls[-1][3]["snippet"]
        self.assertEqual(sent["liveChatId"], "LC")
        self.assertEqual(len(sent["textMessageDetails"]["messageText"]), 200)

    def test_quota_message(self):
        a, _ = self.auth([(403, {"error": {"message": "The request cannot be completed because you have exceeded your quota."}})])
        a._tok = {"access_token": "at", "expires_at": a._now() + 3600, "client_id": "id.apps.googleusercontent.com"}
        ok, why = run(a.send_chat("hi", "LC"))
        self.assertFalse(ok)
        self.assertIn("daily API quota", why)


class YouTubeAdapterSendTests(unittest.TestCase):
    def test_reply_gets_at_name(self):
        sent = []

        class Auth:
            connected = True

            async def live_chat_id(self, vid):
                return "LC", ""

            async def send_chat(self, text, chat_id):
                sent.append((text, chat_id))
                return True, ""

        orig = youtube_mod.get_youtube_auth
        youtube_mod.get_youtube_auth = lambda cfg=None: Auth()
        self.addCleanup(lambda: setattr(youtube_mod, "get_youtube_auth", orig))
        a = YouTubeAdapter({"youtube": {"video_id": "vid"}}, EventBus(), MetricsAggregator({}))
        self.assertEqual(a.can_send(), (True, ""))
        self.assertTrue(run(a.send_message("you have 5 points", reply_to_user="Bob")))
        self.assertEqual(sent, [("@Bob you have 5 points", "LC")])


class FakeAdapter:
    """A platform adapter for main.py's reply routing."""

    def __init__(self, can=True, ok=True):
        self.can, self.ok, self.sent, self.last_send_error = can, ok, [], ""

    def can_send(self):
        return (True, "") if self.can else (False, "not connected")

    async def send_message(self, text, reply_to_message_id="", reply_to_user=""):
        self.sent.append((text, reply_to_message_id))
        return self.ok


class ReplyRoutingTests(unittest.TestCase):
    def core(self, mode="auto", **adapters):
        from main import StreamCore
        from core.store import Store

        core = StreamCore({"replies": {"kick": mode, "twitch": mode, "youtube": mode}})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core.store = Store(Path(tmp.name) / "t.db")
        core.state.config = core.config
        self.shown: list = []

        class WS:
            async def broadcast(_, payload):
                self.shown.append(payload)

        core.state.ws_manager = WS()
        core.adapters.clear()
        core.adapters.update(adapters)
        return core

    def reply(self, plat=Platform.KICK, target=True):
        return ChatReply(platform=plat, message="you have 50 points", reply_to_user="Bob",
                         reply_to_message_id="m9", target_platform=plat if target else None)

    def frames(self, kind):
        return [p for p in self.shown if p.get("type") == kind]

    def test_auto_posts_and_skips_overlay(self):
        kick = FakeAdapter()
        core = self.core(kick=kick)
        run(core._deliver_reply(self.reply()))
        self.assertEqual(kick.sent, [("you have 50 points", "m9")])
        self.assertEqual(self.frames("reply"), [])
        self.assertEqual(core.recent_replies, [])

    def test_auto_falls_back_to_overlay(self):
        for kick in (FakeAdapter(can=False), FakeAdapter(ok=False)):
            self.shown = []
            core = self.core(kick=kick)
            run(core._deliver_reply(self.reply()))
            self.assertEqual(len(self.frames("reply")), 1)
            self.assertFalse(self.frames("reply")[0]["data"]["posted_to_chat"])

    def test_overlay_mode_never_posts(self):
        kick = FakeAdapter()
        core = self.core("overlay", kick=kick)
        run(core._deliver_reply(self.reply()))
        self.assertEqual(kick.sent, [])
        self.assertEqual(len(self.frames("reply")), 1)

    def test_chat_mode_never_shows(self):
        core = self.core("chat", kick=FakeAdapter(ok=False))
        run(core._deliver_reply(self.reply()))
        self.assertEqual(self.shown, [])

    def test_both_mode(self):
        kick = FakeAdapter()
        core = self.core("both", kick=kick)
        run(core._deliver_reply(self.reply()))
        self.assertEqual(len(kick.sent), 1)
        self.assertTrue(self.frames("reply")[0]["data"]["posted_to_chat"])

    def test_announcement_goes_to_every_platform(self):
        kick, twitch = FakeAdapter(), FakeAdapter(can=False)
        core = self.core(kick=kick, twitch=twitch)
        run(core._deliver_reply(self.reply(target=False)))
        self.assertEqual(len(kick.sent), 1)
        # Twitch couldn't post, so the overlay shows it for Twitch's viewers
        self.assertEqual(len(self.frames("reply")), 1)

    def test_bad_mode_means_auto(self):
        core = self.core("sideways")
        self.assertEqual(core._reply_mode("kick"), "auto")

    def test_echo_is_never_a_command(self):
        core = self.core()
        ev = chat_event(Platform.KICK, "!points", "fridge")
        ev.from_core = True
        ran = []

        async def execute(req):
            ran.append(req)

        core.bus.on_execute(execute)
        run(core._on_chat(ev))
        chat = self.frames("chat")
        self.assertTrue(chat and chat[0]["data"]["from_core"] and chat[0]["data"]["is_system"])
        self.assertEqual(ran, [])
        self.assertEqual(self.frames("reply"), [])


if __name__ == "__main__":
    unittest.main()
