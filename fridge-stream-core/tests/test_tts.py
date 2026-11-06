"""Text-to-speech: core/tts.py (queue, server calls, down handling, triggers), core/tts_text.py
(blocked words and clean-up) and api/tts_routes.py, against a fake OpenAI-style server
(httpx.MockTransport), so no real TTS server is needed.

    python -m pytest tests/test_tts.py -q
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DEFAULTS, _deep_merge  # noqa: E402
from core.highlights import HighlightBoard  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.plugin_api import PluginContext  # noqa: E402
from core.store import Store  # noqa: E402
from core.tts import FAIL_LIMIT, TtsEngine, read_settings, speech_url, voices_url  # noqa: E402
from core.tts_text import TextFilter, strip_emotes  # noqa: E402

TOKEN = "tok-123456789abc"
HEAD = {"X-Admin-Token": TOKEN}
AUDIO = b"ID3fake-mp3-bytes"


def run(coro):
    return asyncio.run(coro)


def user(name="nova", mod=False, vip=False, sub=False, platform=Platform.TWITCH):
    return ChatUser(platform=platform, id="u-" + name, username=name, display_name=name.title(),
                    is_mod=mod, is_vip=vip, is_subscriber=sub)


def chat(text, **kw):
    paid = kw.pop("paid", False)
    return ChatEvent(platform=Platform.TWITCH, user=user(**kw), message=text, is_paid=paid)


class FakeServer:
    """An OpenAI-style TTS server: answers POST /v1/audio/speech with audio, or fails on demand."""

    def __init__(self):
        self.calls = []
        self.fail = False
        self.status = 200
        self.voices = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/voices"):
            if self.voices is None:
                return httpx.Response(404)
            return httpx.Response(200, json={"voices": self.voices})
        self.calls.append({"url": str(request.url), "body": json.loads(request.content or b"{}"),
                           "auth": request.headers.get("authorization")})
        if self.fail:
            raise httpx.ConnectError("refused", request=request)
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "bad voice"})
        return httpx.Response(200, content=AUDIO, headers={"content-type": "audio/mpeg"})


def tts_config(**over):
    """A whole config with TTS on and a server address, every trigger on unless switched off."""
    tts = {"enabled": True, "server": {"url": "http://tts-box:8880"}, "voice": "af_bella",
           "triggers": {k: {"enabled": True} for k in ("alerts", "paid", "command", "chat", "highlight", "plugins")}}
    tts["triggers"]["chat"].update({"who": "everyone", "min_gap_sec": 0})
    tts["triggers"]["command"].update({"cooldown_sec": 0})
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(tts.get(key), dict):
            tts[key] = _deep_merge(tts[key], value)
        else:
            tts[key] = value
    return _deep_merge(DEFAULTS, {"tts": tts, "points": {"enabled": True, "per_message": 0, "cooldown_sec": 0}})


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cfg = tts_config()
        self.server = FakeServer()
        self.sent = []
        self.notes = []
        self.store = Store(self.root / "core.db", {"enabled": True, "per_message": 0, "cooldown_sec": 0}, {"enabled": False})

        async def broadcast(p):
            self.sent.append(p)

        self.engine = TtsEngine(
            get_config=lambda: self.cfg, data_dir=self.root, broadcast=broadcast,
            note=lambda kind, text, platform="": self.notes.append((kind, text)),
            store=self.store, is_admin=lambda u: getattr(u, "username", "") == "streamer",
            transport=httpx.MockTransport(self.server),
        )

    def drain(self):
        """Process every queued line (what run() does)."""
        async def go():
            while self.engine.pending:
                await self.engine.process(self.engine.pending.popleft())
        run(go())

    def sent_of(self, kind):
        return [p["data"] for p in self.sent if p["type"] == kind]


class TextTests(unittest.TestCase):
    def test_blocked_words_catch_dodges_but_not_inside_words(self):
        f = TextFilter({"filters": {"blocked": ["idiot*", "go back to", "ass"]}})
        for line in ("you 1d10t", "i.d.i.o.t", "i d i o t lol", "iiidiot", "IDIOTS", "you-idiot", "go back to bed", "Ídiót"):
            self.assertEqual(f.clean(line), ("", "blocked word"), line)
        self.assertEqual(f.clean("first class"), ("first class", ""))

    def test_beep_and_remove(self):
        self.assertEqual(TextFilter({"filters": {"blocked": ["idiot"], "on_match": "beep"}}).clean("you idiot, hi")[0], "you beep, hi")
        self.assertEqual(TextFilter({"filters": {"blocked": ["idiot"], "on_match": "remove"}}).clean("you idiot hi")[0], "you hi")

    def test_names_links_runs_and_length(self):
        f = TextFilter({"filters": {"blocked": ["idiot"]}, "max_chars": 30})
        self.assertEqual(f.clean_name("xX_Idiot_Xx"), "someone")
        self.assertEqual(f.clean_name("Nova_Star"), "Nova Star")
        self.assertEqual(f.clean("noooooooo!!!! https://x.com/a hi")[0], "nooo! hi")
        self.assertEqual(f.clean("www.spam.com")[1], "nothing left to read")
        out = f.clean("one two three four five six seven eight nine")[0]
        self.assertLessEqual(len(out), 30)
        self.assertFalse(out.endswith(" "))

    def test_emotes_are_taken_out(self):
        self.assertEqual(strip_emotes("Kappa hi Kappa", [{"start": 0, "end": 4}, {"start": 9, "end": 13}]), ("hi", True))
        self.assertEqual(strip_emotes("[emote:37226:KEKW] lol"), ("lol", True))
        self.assertEqual(strip_emotes("plain"), ("plain", False))


class SettingsTests(unittest.TestCase):
    def test_defaults_off_and_clamped(self):
        s = read_settings(DEFAULTS)
        self.assertFalse(s["enabled"])
        self.assertTrue(all(not t["enabled"] for t in s["triggers"].values()))
        s = read_settings({"tts": {"speed": 9, "volume": -5, "server": {"format": "ogg", "timeout_sec": 1},
                                   "triggers": {"chat": {"who": "kings", "every_nth": 0}, "command": {"word": "!Say It"}}}})
        self.assertEqual((s["speed"], s["volume"], s["server"]["format"], s["server"]["timeout_sec"]), (2.0, 0, "mp3", 3))
        self.assertEqual((s["triggers"]["chat"]["who"], s["triggers"]["chat"]["every_nth"]), ("mods", 1))
        self.assertEqual(s["triggers"]["command"]["word"], "sayit")

    def test_old_highlight_read_aloud_still_counts(self):
        self.assertTrue(read_settings({"highlight": {"read_aloud": True}})["triggers"]["highlight"]["enabled"])
        self.assertFalse(read_settings({"highlight": {"read_aloud": True}, "tts": {"triggers": {"highlight": {"enabled": False}}}})
                         ["triggers"]["highlight"]["enabled"])

    def test_addresses(self):
        for typed in ("192.168.1.5:8880", "http://192.168.1.5:8880/", "http://192.168.1.5:8880/v1",
                      "http://192.168.1.5:8880/v1/audio/speech"):
            self.assertEqual(speech_url(typed), "http://192.168.1.5:8880/v1/audio/speech")
        self.assertEqual(speech_url("https://api.openai.com/v1"), "https://api.openai.com/v1/audio/speech")
        self.assertEqual(voices_url("http://h:1"), "http://h:1/v1/audio/voices")


class EngineTests(Base):
    def test_a_line_goes_to_the_server_and_the_overlay(self):
        self.cfg["tts"]["server"]["api_key"] = "sk-secret"
        ok, _ = run(self.engine.say_test("Hello chat", "am_adam"))
        self.assertTrue(ok)
        self.drain()
        call = self.server.calls[0]
        self.assertEqual(call["url"], "http://tts-box:8880/v1/audio/speech")
        self.assertEqual(call["body"], {"model": "tts-1", "input": "Hello chat", "voice": "am_adam",
                                        "response_format": "mp3", "speed": 1.0})
        self.assertEqual(call["auth"], "Bearer sk-secret")
        line = self.sent_of("tts")[0]
        self.assertTrue(line["url"].startswith("/tts/") and line["url"].endswith(".mp3"))
        self.assertEqual(self.engine.file_path(line["url"][5:]).read_bytes(), AUDIO)
        self.assertEqual(self.engine.status()["state"], "ok")
        self.assertIsNone(self.engine.file_path("../core.db"))

    def test_backup_address_is_tried(self):
        self.cfg["tts"]["server"]["backup_url"] = "http://backup:9000"

        def handler(request):
            if request.url.host == "tts-box":
                raise httpx.ConnectError("no", request=request)
            return httpx.Response(200, content=AUDIO, headers={"content-type": "audio/wav"})

        self.engine.transport = httpx.MockTransport(handler)
        run(self.engine.say_test("hi"))
        self.drain()
        self.assertTrue(self.sent_of("tts")[0]["url"].endswith(".wav"))

    def test_down_after_three_failures_then_back(self):
        self.server.fail = True
        for i in range(FAIL_LIMIT):
            run(self.engine.say_test(f"line {i}"))
            self.drain()
        st = self.engine.status()
        self.assertEqual(st["state"], "down")
        self.assertIn("Can't reach tts-box", st["last_error"])
        self.assertEqual([k for k, _ in self.notes], ["error"])
        # while down nothing is sent to the server
        calls = len(self.server.calls)
        run(self.engine.say_test("skipped"))
        self.drain()
        self.assertEqual(len(self.server.calls), calls)
        self.server.fail = False
        self.assertTrue(run(self.engine.recheck()))
        self.assertEqual(self.engine.status()["state"], "ok")
        self.assertEqual(self.notes[-1][0], "alert")

    def test_pretend_down(self):
        self.engine.set_pretend_down(True)
        for i in range(FAIL_LIMIT):
            run(self.engine.say_test(f"line {i}"))
            self.drain()
        self.assertTrue(self.engine.status()["down"])
        self.assertEqual(self.server.calls, [])
        self.engine.set_pretend_down(False)
        self.assertTrue(run(self.engine.recheck()))

    def test_server_error_words(self):
        self.server.status = 400
        with self.assertRaisesRegex(Exception, "HTTP 400: bad voice"):
            run(self.engine.test_audio("hi"))
        self.server.status = 401
        with self.assertRaisesRegex(Exception, "refused the API key"):
            run(self.engine.test_audio("hi"))
        # the page's own tests never mark the server down
        self.assertFalse(self.engine.down)

    def test_check_lists_voices(self):
        self.server.voices = ["af_bella", {"id": "am_adam"}]
        r = run(self.engine.check())
        self.assertTrue(r["ok"])
        self.assertEqual(r["voices"], ["af_bella", "am_adam"])


class TriggerTests(Base):
    def alert(self, kind="follow", **kw):
        from core.alerts import build_alert
        return build_alert(kind=kind, username=kw.pop("name", "nova"), platform="twitch", **kw)

    def test_alert_voice_waits_for_its_alert(self):
        p = self.alert("subscribe")
        voice = self.engine.on_alert(p)
        self.assertEqual(voice["wait_ms"], 15000 + 4000)
        self.drain()
        line = self.sent_of("tts")[0]
        self.assertEqual(line["alert_id"], p["id"])
        self.assertEqual(self.server.calls[0]["body"]["input"], "nova subscribed!")

    def test_paid_min_amount_and_missed_list(self):
        self.cfg["tts"]["triggers"]["paid"]["min_amount"] = 5
        self.assertIsNone(self.engine.on_alert(self.alert("superchat", amount=2, message="small")))
        self.assertIsNone(self.engine.on_alert(self.alert("bits", amount=100, currency="bits")))   # = 1
        p = self.alert("superchat", amount=10, message="keep it up")
        self.assertTrue(self.engine.on_alert(p))
        self.server.fail = True
        self.drain()
        self.assertEqual(self.sent_of("tts_skip"), [{"alert_id": p["id"]}])
        self.assertEqual(len(self.engine.missed), 1)
        self.assertIn("keep it up", self.engine.missed[0]["text"])
        # replay once the server is back
        self.server.fail = False
        self.assertEqual(run(self.engine.replay()), 1)
        self.drain()
        self.assertEqual(self.engine.missed, [])
        self.assertEqual(len(self.sent_of("tts")), 1)

    def test_follows_are_not_kept_when_missed(self):
        self.server.fail = True
        self.engine.on_alert(self.alert("follow"))
        self.drain()
        self.assertEqual(self.engine.missed, [])

    def test_test_alerts_only_with_read_aloud(self):
        self.cfg["tts"]["triggers"]["alerts"]["enabled"] = False
        p = self.alert("follow", is_test=True)
        self.assertIsNone(self.engine.on_alert(p))
        p["read_aloud"] = True
        self.assertTrue(self.engine.on_alert(p))
        self.cfg["tts"]["enabled"] = False
        self.assertIsNone(self.engine.on_alert(p))

    def test_blocked_name_and_message(self):
        self.cfg["tts"]["filters"]["blocked"] = ["idiot"]
        self.engine.on_alert(self.alert("follow", name="big_idiot"))
        self.drain()
        self.assertEqual(self.server.calls[-1]["body"]["input"], "someone followed!")
        self.assertIsNone(self.engine.on_alert(self.alert("superchat", amount=5, message="you idiot")))
        self.assertEqual(self.engine.recent[-1]["why"], "blocked word")

    def test_tts_command_costs_points_and_refunds_when_missed(self):
        uid = run(self.store.get_or_create_user("twitch", "u-nova", "nova", "Nova"))
        run(self.store.adjust_points(uid, 150))
        taken, answer = run(self.engine.handle_command(chat("!tts hello there")))
        self.assertEqual((taken, answer), (True, ""))
        self.assertEqual(run(self.store.get_user(uid))["points"], 50)
        taken, answer = run(self.engine.handle_command(chat("!tts again")))
        self.assertIn("costs 100 points, you have 50", answer)
        self.server.fail = True
        self.drain()
        self.assertEqual(run(self.store.get_user(uid))["points"], 150)
        self.assertEqual(self.engine.missed[0]["refunded"], 100)
        self.assertIn("Nova says: hello there", self.engine.missed[0]["text"])

    def test_tts_command_rules(self):
        self.assertEqual(run(self.engine.handle_command(chat("!ttsx hi"))), (False, ""))
        self.assertIn("type !tts", run(self.engine.handle_command(chat("!tts")))[1])
        self.cfg["tts"]["triggers"]["command"]["who"] = "subs"
        self.assertIn("only for subs", run(self.engine.handle_command(chat("!tts hi")))[1])
        self.cfg["tts"]["triggers"]["command"].update(who="everyone", cooldown_sec=60, cost=0)
        self.assertEqual(run(self.engine.handle_command(chat("!tts one"))), (True, ""))
        self.assertIn("again in", run(self.engine.handle_command(chat("!tts two")))[1])
        # the streamer is free and has no cooldown
        self.cfg["tts"]["triggers"]["command"]["cost"] = 500
        self.assertEqual(run(self.engine.handle_command(chat("!tts mine", name="streamer"))), (True, ""))
        self.assertEqual(run(self.engine.handle_command(chat("!tts mine", name="streamer"))), (True, ""))
        # the settings page's pretend chatter costs nothing
        taken, answer = run(self.engine.handle_command(chat("!tts pretend", name="fake"), dry_points=True))
        self.assertIn("would cost 500 points", answer)
        self.cfg["tts"]["triggers"]["command"]["enabled"] = False
        self.assertEqual(run(self.engine.handle_command(chat("!tts off"))), (False, ""))

    def test_clear_refunds_waiting_lines(self):
        uid = run(self.store.get_or_create_user("twitch", "u-nova", "nova", "Nova"))
        run(self.store.adjust_points(uid, 100))
        run(self.engine.handle_command(chat("!tts waiting")))
        self.assertEqual(run(self.engine.clear()), 1)
        self.assertEqual(run(self.store.get_user(uid))["points"], 100)
        self.assertEqual(self.sent_of("tts_control"), [{"action": "clear"}])

    def test_chat_lines_who_turns_and_gap(self):
        self.cfg["tts"]["triggers"]["chat"].update(who="vips", every_nth=2)
        self.assertFalse(self.engine.on_chat(chat("hi")))                    # not a VIP
        self.assertTrue(self.engine.on_chat(chat("one", vip=True)))          # 1st
        self.assertFalse(self.engine.on_chat(chat("two", vip=True)))         # 2nd: not its turn
        self.assertTrue(self.engine.on_chat(chat("three", mod=True)))        # mods count as VIPs
        self.assertFalse(self.engine.on_chat(chat("!cmd", mod=True)))
        self.assertFalse(self.engine.on_chat(chat("paid", mod=True, paid=True)))
        self.cfg["tts"]["triggers"]["chat"].update(every_nth=1, min_gap_sec=60)
        self.assertFalse(self.engine.on_chat(chat("four", vip=True)))        # too soon after "three"
        self.engine._chat_last = time.time() - 61
        self.assertTrue(self.engine.on_chat(chat("five", vip=True)))

    def test_highlight_read_aloud(self):
        board = HighlightBoard(self.cfg)
        board.on_shown = self.engine.on_highlight
        board.push({"platform": "twitch", "message_id": "m1", "message": "Kappa great stream",
                    "emotes": [{"start": 0, "end": 4, "url": "https://x/e.png", "name": "Kappa"}],
                    "user": {"id": "1", "username": "moth", "display_name": "Moth"}})
        self.drain()
        self.assertEqual(self.server.calls[0]["body"]["input"], "Moth says: great stream")

    def test_plugin_say(self):
        class Bus:
            pass

        bus = Bus()
        bus.say = self.engine.say_plugin
        ctx = PluginContext(id="schedule1", folder=self.root, root=self.root, data_dir=self.root, bus=bus)
        self.assertTrue(run(ctx.say("Cash drop at the docks", voice="bm_george")))
        self.drain()
        self.assertEqual(self.server.calls[0]["body"]["voice"], "bm_george")
        self.cfg["tts"]["triggers"]["plugins"]["enabled"] = False
        self.assertFalse(run(ctx.say("nope")))
        self.assertFalse(run(PluginContext(id="x", folder=self.root, root=self.root, data_dir=self.root).say("no bus")))


class LiveControlTests(Base):
    """Work list item 19: blocked chatters, pause, off for N minutes, drop, long lines, glow."""

    def test_blocked_chatter_is_not_read(self):
        self.engine.on_chat(chat("first", name="loudguy"))
        self.assertEqual(len(self.engine.pending), 1)
        self.assertIsNotNone(self.engine.block("twitch", "LoudGuy", "day"))
        self.assertEqual(len(self.engine.pending), 0)                 # their waiting line went too
        self.assertFalse(self.engine.on_chat(chat("again", name="loudguy")))
        taken, answer = run(self.engine.handle_command(chat("!tts hi", name="loudguy")))
        self.assertTrue(taken)
        self.assertIn("isn't available", answer)
        self.assertTrue(self.engine.on_chat(chat("fine", name="nova")))  # others still read
        # "day" and "forever" are saved, "stream" isn't
        self.engine.block("kick", "streamonly", "stream")
        again = TtsEngine(get_config=lambda: self.cfg, data_dir=self.root)
        self.assertTrue(again.is_blocked("twitch:loudguy"))
        self.assertFalse(again.is_blocked("kick:streamonly"))
        self.assertTrue(self.engine.unblock("twitch:loudguy"))
        self.assertTrue(self.engine.on_chat(chat("back", name="loudguy")))
        self.assertIsNone(self.engine.block("twitch", "  ", "day"))

    def test_day_block_runs_out(self):
        self.engine.block("twitch", "nova", "day")
        self.engine.blocked_people["twitch:nova"]["until"] = time.time() - 1
        self.assertFalse(self.engine.is_blocked("twitch:nova"))

    def test_quiet_drops_and_refuses_then_comes_back(self):
        self.engine.on_chat(chat("one", name="a"))
        dropped = run(self.engine.quiet_for(15))
        self.assertEqual(dropped, 1)
        self.assertTrue(self.engine.status()["quiet_until"] > time.time() + 800)
        self.assertFalse(self.engine.on_chat(chat("two", name="b")))
        taken, _answer = run(self.engine.handle_command(chat("!tts hello", name="streamer")))   # free
        self.assertTrue(taken)
        self.assertEqual(self.engine.missed[-1]["why"], "read aloud off for a while")
        run(self.engine.quiet_for(0))
        self.assertTrue(self.engine.on_chat(chat("three", name="d")))

    def test_pause_holds_and_drop(self):
        self.engine.set_paused(True)
        self.engine.on_chat(chat("one", name="a"))
        self.engine.on_chat(chat("two", name="b"))
        st = self.engine.status()
        self.assertTrue(st["paused"])
        self.assertEqual(len(st["next"]), 2)
        self.assertTrue(run(self.engine.drop(st["next"][0]["id"])))
        self.assertEqual(len(self.engine.pending), 1)
        self.assertFalse(run(self.engine.drop(9999)))

    def test_long_lines_cut_or_skip(self):
        self.cfg["tts"]["max_chars"] = 40
        self.assertTrue(self.engine.on_chat(chat("word " * 30, name="a")))
        self.assertLessEqual(len(self.engine.pending[-1].text), 40)
        self.cfg["tts"]["long_lines"] = "skip"
        self.assertFalse(self.engine.on_chat(chat("word " * 30, name="b")))
        self.assertTrue(self.engine.on_chat(chat("short", name="c")))

    def test_speaking_packet_for_stream_rooms(self):
        self.engine.on_chat(chat("hello there", name="Nova"))
        self.drain()
        sp = self.sent_of("tts_speaking")
        self.assertEqual(sp[0]["platform"], "twitch")
        self.assertEqual(sp[0]["username"], "nova")
        self.assertGreaterEqual(sp[0]["seconds"], 2.0)
        self.assertEqual(self.engine.status()["now"]["trigger"], "chat")


class RouteTests(Base):
    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.server import CoreState
        from api.tts_routes import create_tts_router

        self.cfg["points"]["admin_token"] = TOKEN
        self.state = CoreState()
        self.state.config = self.cfg
        self.state.tts = self.engine
        self.engine.get_config = lambda: self.state.config
        self.saved = []
        # config.yaml is never written by the tests: save_config is swapped for a list
        import api.tts_routes as routes
        self.addCleanup(setattr, routes, "save_config", routes.save_config)
        routes.save_config = lambda cfg: self.saved.append(json.loads(json.dumps(cfg)))
        app = FastAPI()
        app.include_router(create_tts_router(self.state, self.root))
        self.client = TestClient(app)

    def test_needs_the_token(self):
        self.assertEqual(self.client.get("/api/admin/tts").status_code, 401)

    def test_key_is_hidden_and_kept(self):
        r = self.client.put("/api/admin/tts/settings", headers=HEAD,
                            json={"server": {"url": "http://box:8880", "api_key": "sk-1"}, "voice": "af_sky"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("sk-1", r.text)
        self.assertTrue(r.json()["settings"]["server"]["api_key_set"])
        self.client.put("/api/admin/tts/settings", headers=HEAD, json={"server": {"url": "http://box:9999", "api_key": ""}})
        self.assertEqual(self.state.config["tts"]["server"]["api_key"], "sk-1")
        self.client.put("/api/admin/tts/settings", headers=HEAD, json={"server": {"api_key_clear": True}})
        self.assertEqual(self.state.config["tts"]["server"]["api_key"], "")
        self.assertEqual(self.saved[-1]["tts"]["server"]["url"], "http://box:9999")

    def test_highlight_switch_written_to_old_home(self):
        self.client.put("/api/admin/tts/settings", headers=HEAD, json={"triggers": {"highlight": {"enabled": False}}})
        self.assertFalse(self.state.config["highlight"]["read_aloud"])
        self.assertTrue(self.state.config["tts"]["triggers"]["chat"]["enabled"])     # other triggers kept

    def test_tools(self):
        r = self.client.post("/api/admin/tts/test", headers=HEAD, json={"text": "hi"})
        self.assertEqual((r.status_code, r.content, r.headers["content-type"]), (200, AUDIO, "audio/mpeg"))
        self.cfg["tts"]["filters"]["blocked"] = ["idiot"]
        r = self.client.post("/api/admin/tts/filter-test", headers=HEAD, json={"text": "you idiot", "name": "x_idiot"})
        self.assertEqual(r.json(), {"text": "", "why": "blocked word", "name": "someone"})
        self.assertEqual(self.client.post("/api/admin/tts/say", headers=HEAD, json={"text": "you idiot"}).status_code, 400)
        r = self.client.post("/api/admin/tts/fake", headers=HEAD, json={"kind": "command", "text": "hello", "name": "Pat"})
        self.assertTrue(r.json()["ok"])
        self.assertIn("would cost 100 points", r.json()["answer"])
        r = self.client.post("/api/admin/tts/pretend-down", headers=HEAD, json={"on": True})
        self.assertTrue(r.json()["status"]["pretend_down"])
        self.server.fail = True
        self.assertFalse(self.client.post("/api/admin/tts/check", headers=HEAD).json()["ok"])
        r = self.client.post("/api/admin/tts/test", headers=HEAD, json={"text": "hi"})
        self.assertEqual(r.status_code, 502)


if __name__ == "__main__":
    unittest.main()
