"""Video requests and the Discord bot: core/video_requests.py (links, rules, queue order, playing,
auto-play, Stream Rooms' end count), core/discord_bot.py (a request from a channel message, the
reactions, the mod buttons and who may press them, the gateway login and a fatal close) and
api/video_request_routes.py (settings save keeps the token hidden, the player page routes).

No network: YouTube look-ups are a fake, Discord's REST API is an httpx.MockTransport and the
gateway is driven by calling the bot's handlers with the messages Discord would send.

    python -m pytest tests/test_video_requests.py -q
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.discord_bot import FATAL_CLOSE, DiscordBot, public_settings  # noqa: E402
from core.discord_bot import read_settings as read_discord  # noqa: E402
from core.video_requests import (VideoRequestQueue, find_youtube_link, fmt_length,  # noqa: E402
                                 read_settings, youtube_id)

VID = "dQw4w9WgXcQ"


def run(coro):
    return asyncio.run(coro)


def fake_lookup(table=None):
    """A stand-in for look_up: every id is a 3-minute embeddable video unless the table says else."""
    table = table or {}

    async def lookup(vid, client=None):
        base = {"ok": True, "title": f"Video {vid}", "channel": "Some channel", "thumb": "", "length": 180,
                "live": False, "embeddable": True, "age_limited": False, "error": ""}
        base.update(table.get(vid, {}))
        return base
    return lookup


class Setup:
    def make(self, vr=None, discord=None, lookup=None, rooms=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {"video_requests": {"enabled": True, **(vr or {})},
                       "discord": {"enabled": True, "token": "tok", "request_channel_id": "100", "mod_channel_id": "200",
                                   **(discord or {})}}
        self.stages = []
        self.rooms = rooms if rooms is not None else {}

        async def send_stage(action, value):
            self.stages.append((action, value))
            return True
        self.q = VideoRequestQueue(lambda: self.config, Path(self.tmp.name), send_stage=send_stage,
                                   rooms_state=lambda: self.rooms, lookup=lookup or fake_lookup())
        return self.q


class LinkTest(unittest.TestCase):
    def test_youtube_links(self):
        for url in (f"https://www.youtube.com/watch?v={VID}", f"https://youtu.be/{VID}?t=3", f"https://youtube.com/shorts/{VID}",
                    f"https://m.youtube.com/watch?v={VID}&list=x", f"https://www.youtube.com/embed/{VID}"):
            self.assertEqual(youtube_id(url), VID, url)
        for url in ("https://vimeo.com/123", "https://www.youtube.com/watch?v=short", "not a link", "https://evil.com/watch?v=" + VID):
            self.assertEqual(youtube_id(url), "", url)
        self.assertEqual(find_youtube_link(f"look at this (https://youtu.be/{VID}) lol"), f"https://youtu.be/{VID}")
        self.assertEqual(find_youtube_link("https://example.com nothing"), "")

    def test_settings_are_cleaned(self):
        s = read_settings({"video_requests": {"max_seconds": "-5", "play_on": "tv", "blocked_words": "Foo, bar ,"}})
        self.assertEqual(s["max_seconds"], 0)
        self.assertEqual(s["play_on"], "player")
        self.assertEqual(s["blocked_words"], ["foo", "bar"])
        self.assertEqual(fmt_length(3725), "1:02:05")
        self.assertEqual(fmt_length(None), "?")


class QueueTest(unittest.TestCase, Setup):
    def test_off_refuses(self):
        q = self.make(vr={"enabled": False})
        self.assertFalse(run(q.submit(f"https://youtu.be/{VID}", "ann"))["ok"])

    def test_rules(self):
        q = self.make(vr={"max_seconds": 120, "blocked_words": ["badword"]},
                      lookup=fake_lookup({"aaaaaaaaaaa": {"length": 100}, "bbbbbbbbbbb": {"length": 999},
                                          "ccccccccccc": {"live": True}, "ddddddddddd": {"age_limited": True},
                                          "eeeeeeeeeee": {"title": "A BadWord video", "length": 10},
                                          "fffffffffff": {"embeddable": False, "length": 10}}))
        self.assertTrue(run(q.submit("https://youtu.be/aaaaaaaaaaa", "ann", by_id="1"))["ok"])
        r = run(q.submit("https://youtu.be/bbbbbbbbbbb", "bob", by_id="2"))
        self.assertIn("limit", r["reason"])
        self.assertIn("Live", run(q.submit("https://youtu.be/ccccccccccc", "cy", by_id="3"))["reason"])
        self.assertIn("Age", run(q.submit("https://youtu.be/ddddddddddd", "di", by_id="4"))["reason"])
        self.assertFalse(run(q.submit("https://youtu.be/eeeeeeeeeee", "ed", by_id="5"))["ok"])
        self.assertIn("outside YouTube", run(q.submit("https://youtu.be/fffffffffff", "fi", by_id="6"))["reason"])
        # one waiting per person; the same video twice is refused
        self.assertIn("already have", run(q.submit("https://youtu.be/ggggggggggg", "ann", by_id="1"))["reason"])
        self.assertIn("already in the queue", run(q.submit("https://youtu.be/aaaaaaaaaaa", "zed", by_id="9"))["reason"])
        # the streamer's own Add skips the per-person rules
        mine = run(q.submit("https://youtu.be/ggggggggggg", "Streamer", source="dashboard", bypass_rules=True))
        self.assertTrue(mine["ok"])
        self.assertEqual(mine["item"]["status"], "approved")  # the streamer's own Add skips the yes

    def test_order_play_and_auto_play(self):
        q = self.make(vr={"auto_play": True})
        a = run(q.submit("https://youtu.be/aaaaaaaaaaa", "ann", by_id="1"))["item"]
        b = run(q.submit("https://youtu.be/bbbbbbbbbbb", "bob", by_id="2"))["item"]
        c = run(q.submit("https://youtu.be/ccccccccccc", "cy", by_id="3"))["item"]
        self.assertEqual([i["id"] for i in q.waiting("pending")], [a["id"], b["id"], c["id"]])
        q.approve(c["id"])
        q.approve(a["id"])
        self.assertEqual([i["id"] for i in q.waiting("approved")], [c["id"], a["id"]], "approved in the order of the yes")
        q.move(a["id"], -1)
        self.assertEqual([i["id"] for i in q.waiting("approved")], [a["id"], c["id"]])
        self.assertFalse(q.approve(a["id"])["ok"], "a second yes is refused")
        q.deny(b["id"], reason="Too long")
        self.assertEqual(q.get(b["id"])["status"], "denied")
        # play next -> the player page sees it; its end plays the next one (auto-play)
        seq0 = q.player_state()["seq"]
        run(q.play())
        ps = q.player_state()
        self.assertEqual(ps["current"]["video_id"], "aaaaaaaaaaa")
        self.assertGreater(ps["seq"], seq0)
        run(q.ended(999))     # an old page's late report: ignored
        self.assertEqual(q.playing()["id"], a["id"])
        run(q.ended(a["id"]))
        self.assertEqual(q.get(a["id"])["status"], "played")
        self.assertEqual(q.playing()["id"], c["id"])
        run(q.failed(c["id"], "removed"))
        self.assertEqual(q.get(c["id"])["status"], "failed")
        self.assertIsNone(q.playing())
        # played once this session -> refused again
        self.assertIn("already played", run(q.submit("https://youtu.be/aaaaaaaaaaa", "zed", by_id="9"))["reason"])

    def test_play_now_skips_the_current_one(self):
        q = self.make()
        a = run(q.submit("https://youtu.be/aaaaaaaaaaa", "ann", by_id="1"))["item"]
        b = run(q.submit("https://youtu.be/bbbbbbbbbbb", "bob", by_id="2"))["item"]
        run(q.play(a["id"]))
        run(q.play(b["id"]))
        self.assertEqual(q.get(a["id"])["status"], "skipped")
        self.assertEqual(q.playing()["id"], b["id"])
        run(q.skip())
        self.assertIsNone(q.playing())

    def test_saved_and_loaded(self):
        q = self.make()
        a = run(q.submit("https://youtu.be/aaaaaaaaaaa", "ann", by_id="1"))["item"]
        q.approve(a["id"])
        run(q.play())
        again = VideoRequestQueue(lambda: self.config, Path(self.tmp.name), lookup=fake_lookup())
        self.assertEqual(again.get(a["id"])["status"], "approved", "playing at shutdown comes back as approved")
        b = run(again.submit("https://youtu.be/bbbbbbbbbbb", "bob", by_id="2"))["item"]
        self.assertGreater(b["id"], a["id"], "ids keep counting up")

    def test_stream_rooms_download_mode(self):
        self.rooms = {"video": {"ended_n": 4}}
        q = self.make(vr={"play_on": "rooms", "auto_play": True}, rooms=self.rooms)
        a = run(q.submit("https://youtu.be/aaaaaaaaaaa", "ann", by_id="1"))["item"]
        b = run(q.submit("https://youtu.be/bbbbbbbbbbb", "bob", by_id="2"))["item"]

        async def flow():
            q.approve(a["id"])
            await asyncio.sleep(0)
            self.assertIn(("video_prep", a["url"]), self.stages, "the first approved video is prepared ahead")
            q.approve(b["id"])
            await q.play()
            await asyncio.sleep(0)
            self.assertIn(("video", a["url"]), self.stages)
            self.assertIn(("video_prep", b["url"]), self.stages, "then the next one")
            self.assertIsNone(q.player_state()["current"], "the player page stays empty in this mode")
            stop = asyncio.Event()
            task = asyncio.create_task(q.watch_rooms(stop))
            await asyncio.sleep(1.2)
            self.assertEqual(q.playing()["id"], a["id"], "same end count: still playing")
            self.rooms["video"]["ended_n"] = 5
            await asyncio.sleep(1.2)
            self.assertEqual(q.get(a["id"])["status"], "played")
            self.assertEqual(q.playing()["id"], b["id"], "auto-play started the next")
            stop.set()
            await task
        run(flow())


class DiscordTest(unittest.TestCase, Setup):
    def make_bot(self, **kw):
        q = self.make(**kw)
        self.calls = []
        self.next_id = 500

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else None
            self.calls.append((request.method, request.url.path, body))
            if request.method == "POST" and request.url.path.endswith("/messages"):
                self.next_id += 1
                return httpx.Response(200, json={"id": str(self.next_id)})
            return httpx.Response(204)
        bot = DiscordBot(lambda: self.config, q, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        bot.status = {"state": "online", "text": "Online."}
        return bot

    def msg(self, content, channel="100", author_id="7", roles=None):
        return {"id": "900", "channel_id": channel, "content": content,
                "author": {"id": author_id, "username": "ann_u", "global_name": "Ann"},
                "member": {"nick": None, "roles": roles or []}}

    def paths(self, method=None):
        return [p for m, p, _ in self.calls if method is None or m == method]

    def test_request_from_channel(self):
        bot = self.make_bot()

        async def flow():
            await bot.on_message(self.msg(f"please play https://youtu.be/{VID}"))
            await asyncio.sleep(0.05)
        run(flow())
        item = bot.queue.waiting("pending")[0]
        self.assertEqual(item["by"], "Ann")
        self.assertEqual(item["ref"]["message_id"], "900")
        self.assertTrue(any("/reactions/" in p and p.startswith("/api/v10/channels/100/messages/900") for p in self.paths("PUT")), "⏳ added")
        posted = [b for m, p, b in self.calls if m == "POST" and p == "/api/v10/channels/200/messages"]
        self.assertEqual(len(posted), 1, "one mod-channel message")
        labels = [c["label"] for c in posted[0]["components"][0]["components"]]
        self.assertEqual(labels, ["Approve", "Deny", "Play now"])
        self.assertEqual(posted[0]["allowed_mentions"], {"parse": []}, "titles can't ping anyone")
        self.assertEqual(item["ref"]["mod_message_id"], "501")

    def test_other_channels_and_bots_are_ignored(self):
        bot = self.make_bot()
        run(bot.on_message(self.msg(f"https://youtu.be/{VID}", channel="999")))
        m = self.msg(f"https://youtu.be/{VID}")
        m["author"]["bot"] = True
        run(bot.on_message(m))
        self.assertEqual(bot.queue.waiting(), [])

    def test_refusal_replies(self):
        bot = self.make_bot(vr={"max_seconds": 60})
        run(bot.on_message(self.msg(f"https://youtu.be/{VID}")))
        replies = [b for m, p, b in self.calls if m == "POST" and p == "/api/v10/channels/100/messages"]
        self.assertTrue(replies and "limit" in replies[0]["content"])
        self.assertEqual(replies[0]["message_reference"]["message_id"], "900")

    def test_requester_roles(self):
        bot = self.make_bot(discord={"requester_role_ids": ["55"]})
        run(bot.on_message(self.msg(f"https://youtu.be/{VID}", roles=["11"])))
        self.assertEqual(bot.queue.waiting(), [])
        run(bot.on_message(self.msg(f"https://youtu.be/{VID}", roles=["55"])))
        self.assertEqual(len(bot.queue.waiting()), 1)

    def test_clean_channel(self):
        bot = self.make_bot(discord={"clean_channel": True})
        run(bot.on_message(self.msg("just chatting")))
        self.assertIn("/api/v10/channels/100/messages/900", self.paths("DELETE"))

    def press(self, bot, act, rid, perms="0", roles=None):
        return {"type": 3, "id": "77", "token": "itok", "data": {"custom_id": f"vr:{act}:{rid}"},
                "member": {"permissions": perms, "roles": roles or [], "nick": "Mod Max", "user": {"id": "3", "username": "max"}}}

    def test_buttons_and_permissions(self):
        bot = self.make_bot(discord={"approver_role_ids": ["42"]})

        async def flow():
            await bot.on_message(self.msg(f"https://youtu.be/{VID}"))
            await asyncio.sleep(0.05)
            rid = bot.queue.waiting()[0]["id"]
            # a viewer without rights gets a private "no"
            await bot.on_interaction(self.press(bot, "approve", rid))
            self.assertEqual(bot.queue.get(rid)["status"], "pending")
            answer = [b for m, p, b in self.calls if p.endswith("/callback")][-1]
            self.assertEqual(answer["type"], 4)
            self.assertEqual(answer["data"]["flags"], 64)
            # an approver role may
            await bot.on_interaction(self.press(bot, "approve", rid, roles=["42"]))
            await asyncio.sleep(0.05)
            self.assertEqual(bot.queue.get(rid)["status"], "approved")
            self.assertEqual(bot.queue.get(rid)["decided_by"], "Mod Max")
            answer = [b for m, p, b in self.calls if p.endswith("/callback")][-1]
            self.assertEqual(answer["type"], 7, "the button's message is edited")
            self.assertIn("Approved by Mod Max", answer["data"]["content"])
            # Manage Server permission may deny
            await bot.on_interaction(self.press(bot, "deny", rid, perms=str(1 << 5)))
            await asyncio.sleep(0.05)
            self.assertEqual(bot.queue.get(rid)["status"], "denied")
            self.assertTrue(any("Not this time" in (b or {}).get("content", "") for m, p, b in self.calls if m == "POST"))
        run(flow())

    def test_gateway_login_and_fatal_close(self):
        bot = self.make_bot()
        sent = []

        class FakeWs:
            async def send(self, text):
                sent.append(json.loads(text))

            async def close(self, code=1000):
                sent.append({"closed": code})
        bot._ws = FakeWs()

        async def flow():
            await bot._handle({"op": 10, "d": {"heartbeat_interval": 45000}})
            await bot._handle({"op": 0, "s": 1, "t": "READY", "d": {"user": {"id": "123", "username": "ReqBot"},
                                                                      "guilds": [{"id": "9", "name": "My server"}]}})
            bot._hb_task.cancel()
        run(flow())
        ident = sent[0]
        self.assertEqual(ident["op"], 2)
        self.assertEqual(ident["d"]["token"], "tok")
        self.assertTrue(ident["d"]["intents"] & (1 << 15), "asks for message content")
        st = bot.public_status()
        self.assertEqual(st["state"], "online")
        self.assertIn("client_id=123", st["invite"])
        self.assertEqual(st["guilds"], [{"id": "9", "name": "My server"}])
        self.assertIn("Message Content Intent", FATAL_CLOSE[4014])

    def test_token_never_leaves(self):
        s = read_discord({"discord": {"token": " abc ", "approver_role_ids": [1, ""]}})
        self.assertEqual(s["token"], "abc")
        self.assertEqual(s["approver_role_ids"], ["1"])
        pub = public_settings(s)
        self.assertNotIn("token", pub)
        self.assertTrue(pub["token_set"])


class RoutesTest(unittest.TestCase, Setup):
    def test_settings_and_player_routes(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.video_request_routes import create_video_request_router

        q = self.make()
        TOKEN = "tok-123456789abc"
        state = type("S", (), {})()
        state.config = {**self.config, "points": {"admin_token": TOKEN}}
        state.video_requests = q
        q._get_config = lambda: state.config
        state.discord = DiscordBot(lambda: state.config, q)
        app = FastAPI()
        app.include_router(create_video_request_router(state, Path(self.tmp.name)))
        saved = {}
        import api.video_request_routes as routes
        # never write the real config.yaml; put the real save back after this test
        real_save = routes.save_config
        self.addCleanup(setattr, routes, "save_config", real_save)
        routes.save_config = lambda cfg: saved.update(cfg)
        c = TestClient(app)
        head = {"X-Admin-Token": TOKEN}
        self.assertEqual(c.get("/api/admin/video-requests").status_code, 401)
        r = c.get("/api/admin/video-requests", headers=head).json()
        self.assertTrue(r["discord"]["settings"]["token_set"])
        self.assertNotIn("token", r["discord"]["settings"])
        # saving without a token keeps the old one; the rules are cleaned
        state.discord.restart = lambda: asyncio.sleep(0)
        r = c.put("/api/admin/video-requests/settings", headers=head,
                  json={"discord": {"guild_id": "9", "token_set": True}, "video_requests": {"max_seconds": 300, "play_on": "x"}}).json()
        self.assertEqual(saved["discord"]["token"], "tok")
        self.assertEqual(saved["discord"]["guild_id"], "9")
        self.assertEqual(saved["video_requests"]["max_seconds"], 300)
        self.assertEqual(saved["video_requests"]["play_on"], "player")
        # add (dashboard), play, the player sees it and reports the end
        r = c.post("/api/admin/video-requests/add", headers=head, json={"url": f"https://youtu.be/{VID}"})
        self.assertEqual(r.status_code, 200, r.text)
        # the streamer's own Add lands approved ("Up next"), so a second yes is refused
        rid = r.json()["queue"]["approved"][0]["id"]
        self.assertEqual(c.post("/api/admin/video-requests/approve", headers=head, json={"id": rid}).status_code, 409)
        self.assertEqual(c.post("/api/admin/video-requests/play", headers=head, json={}).status_code, 200)
        p = c.get("/api/video-requests/player").json()
        self.assertEqual(p["current"]["video_id"], VID)
        c.post("/api/video-requests/player/ended", json={"id": rid})
        self.assertIsNone(c.get("/api/video-requests/player").json()["current"])
        self.assertEqual(q.get(rid)["status"], "played")
        self.assertEqual(c.post("/api/admin/video-requests/skip", headers=head).status_code, 409, "nothing playing")


if __name__ == "__main__":
    unittest.main()
